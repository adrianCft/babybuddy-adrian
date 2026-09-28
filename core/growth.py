"""WHO 2006 LMS curves, using the daily tables already shipped in the project."""

import csv
import math
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist

from django.utils import timezone
from django.utils.translation import gettext as _

from core import models

NORMAL = NormalDist()
MAX_AGE = 1826  # Five years; do not extrapolate beyond the WHO infant standard.
FACTORS = {
    "weight": {"kg": 1, "g": 0.001},
    "height": {"cm": 1},
    "head_circumference": {"cm": 1},
}
REFERENCE_MAX_AGE = {"aragon": 730, "who": MAX_AGE}


@lru_cache(maxsize=4)
def reference(kind, sex):
    if kind not in FACTORS or sex not in {"boy", "girl"}:
        return {}
    path = Path(__file__).parent / "migrations" / f"{kind}_percentile_{sex}s.csv"
    with path.open(encoding="utf-8", newline="") as source:
        return {
            int(row.get("Age", row.get("Day"))): tuple(
                float(row[key]) for key in ("L", "M", "S")
            )
            for row in csv.DictReader(source)
        }


def z_score(value, lms):
    l, m, s = lms
    if not math.isfinite(value) or value <= 0:
        return None
    return math.log(value / m) / s if l == 0 else ((value / m) ** l - 1) / (l * s)


def measurement_at(z, lms):
    l, m, s = lms
    if l == 0:
        return m * math.exp(s * z)
    base = 1 + l * s * z
    return m * base ** (1 / l) if base > 0 else None


def percentile_label(z):
    value = NORMAL.cdf(z) * 100
    if value < 0.1:
        return "< P0.1"
    if value > 99.9:
        return "> P99.9"
    return f"P{value:.1f}"


def age_at(child, profile, day):
    age = (day - child.birth_date).days
    corrected = False
    if profile.birth_status == "preterm" and age < 731:
        if profile.gestational_weeks is None:
            return None, False
        age -= 280 - profile.gestational_weeks * 7 - profile.gestational_days
        corrected = True
    return age, corrected


def build_growth(child, user, as_of=None):
    as_of = as_of or timezone.localdate()
    profile = getattr(child, "growth_profile", None) or models.GrowthProfile(
        child=child
    )
    maximum_age = REFERENCE_MAX_AGE.get(profile.reference_system, 730)
    result = {
        "child": child,
        "profile": profile,
        "as_of": as_of,
        "maximum_age": maximum_age,
        "reference_label": profile.get_reference_system_display(),
        "metrics": [],
    }
    for kind, model, permission, label, unit in [
        ("weight", models.Weight, "weight", _("Weight"), "kg"),
        ("height", models.Height, "height", _("Length / height"), "cm"),
        (
            "head_circumference",
            models.HeadCircumference,
            "headcircumference",
            _("Head Circumference"),
            "cm",
        ),
    ]:
        if not user.has_perm(f"core.view_{permission}"):
            continue
        chosen_unit = getattr(profile, f"{kind}_unit", unit)
        factor = FACTORS[kind].get(chosen_unit)
        table = reference(kind, profile.sex)
        metric = {
            "kind": kind,
            "label": label,
            "unit": unit,
            "input_unit": chosen_unit,
            "rows": [],
            "projection": None,
        }
        records = model.objects.filter(child=child, date__lte=as_of).order_by(
            "date", "pk"
        )
        for row in records:
            age, corrected = age_at(child, profile, row.date)
            value = getattr(row, kind)
            point = {
                "date": row.date,
                "input": value,
                "age": age,
                "corrected": corrected,
                "percentile": None,
                "value": None,
            }
            if (
                factor
                and table
                and age is not None
                and 0 <= age <= maximum_age
                and row.date >= child.birth_date
            ):
                converted = value * factor
                z = z_score(converted, table[age])
                if z is not None:
                    point.update(value=converted, z=z, percentile=percentile_label(z))
            metric["rows"].append(point)
        valid = [row for row in metric["rows"] if row["percentile"] is not None]
        metric["latest"] = metric["rows"][-1] if metric["rows"] else None
        # Repeated measurements on a date remain visible but are one observation.
        distinct = list({row["date"]: row for row in valid}.values())
        if len(distinct) > 1 and metric["latest"] == distinct[-1]:
            previous, latest = distinct[-2:]
            metric["previous"] = previous
            metric["change"] = round(
                (NORMAL.cdf(latest["z"]) - NORMAL.cdf(previous["z"])) * 100, 1
            )
        target = as_of + timedelta(days=30)
        target_age, target_corrected = age_at(child, profile, target)
        latest = metric["latest"]
        enough = (
            len(distinct) >= 2
            and (distinct[-1]["date"] - distinct[0]["date"]).days >= 14
        )
        metric["projection_reason"] = _(
            "A scenario needs two valid dates at least 14 days apart, a measurement in the last 60 days and a confirmed birth history."
        )
        if (
            enough
            and latest in valid
            and profile.birth_status
            and (as_of - latest["date"]).days <= 60
            and abs(latest["z"]) <= 3
            and target_age is not None
            and 0 <= target_age <= maximum_age
            and target_corrected == latest["corrected"]
            and (kind != "height" or (latest["age"] < 731) == (target_age < 731))
        ):
            projected = measurement_at(latest["z"], table[target_age])
            if projected is not None:
                metric["projection"] = {
                    "date": target,
                    "age": target_age,
                    "value": projected,
                    "percentile": latest["percentile"],
                }
        elif enough:
            metric["projection_reason"] = _(
                "Scenario unavailable: check recency, birth history and the reference age range. Scenarios do not cross changes in age correction or measurement method, or extend extreme values."
            )
        metric["chart"] = build_chart(
            valid, metric["projection"], table, kind, maximum_age
        )
        metric["rows"].reverse()
        result["metrics"].append(metric)
    return result


def build_chart(points, projection, table, kind, maximum_age=MAX_AGE):
    if not points:
        return None
    # Plot chronological dates: corrected-age curves can be discontinuous at 2y.
    # Keep a single measurement/age regime in a chart; full history stays below.
    latest = points[-1]
    points = [
        p
        for p in points
        if p["corrected"] == latest["corrected"]
        and (kind != "height" or (p["age"] < 731) == (latest["age"] < 731))
    ]
    low = max(0, min(p["age"] for p in points) - 7)
    high = min(
        maximum_age,
        max(projection["age"] if projection else latest["age"], low + 14),
    )
    if kind == "height":
        low, high = (
            (low, min(high, 730)) if latest["age"] < 731 else (max(low, 731), high)
        )
    ages = sorted(
        set([low, high] + list(range(low, high + 1, max(1, (high - low) // 80))))
    )
    curves = [
        (
            p,
            [
                (age, measurement_at(NORMAL.inv_cdf(p / 100), table[age]))
                for age in ages
            ],
        )
        for p in (3, 15, 50, 85, 97)
    ]
    values = [p["value"] for p in points] + [
        value for _, curve in curves for _, value in curve
    ]
    if projection:
        values.append(projection["value"])
    minimum, maximum = min(values) * 0.95, max(values) * 1.05

    def position(age, value):
        return (
            55 + (age - low) / max(1, high - low) * 620,
            220 - (value - minimum) / max(0.01, maximum - minimum) * 190,
        )

    def path(items):
        return " ".join(
            f"{x:.2f},{y:.2f}"
            for x, y in (position(age, value) for age, value in items)
        )

    offset = latest["date"] - timedelta(days=latest["age"])
    return {
        "curves": [
            {
                "label": f"P{p}",
                "points": path(curve),
                "y": f"{position(*curve[-1])[1]:.2f}",
            }
            for p, curve in curves
        ],
        "line": path([(p["age"], p["value"]) for p in points]),
        "points": [
            {
                "x": f"{position(p['age'], p['value'])[0]:.2f}",
                "y": f"{position(p['age'], p['value'])[1]:.2f}",
                **p,
            }
            for p in points
        ],
        "forecast": (
            path(
                [
                    (latest["age"], latest["value"]),
                    (projection["age"], projection["value"]),
                ]
            )
            if projection
            else None
        ),
        "first": offset + timedelta(days=low),
        "last": offset + timedelta(days=high),
        "minimum": minimum,
        "maximum": maximum,
    }
