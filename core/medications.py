from urllib.parse import urlencode

from django.urls import reverse

from core.navigation import contextual_url


def prescription_dose_url(request, prescription):
    query = urlencode(
        {"prescription": prescription.pk, "child": prescription.visit.child.slug}
    )
    return contextual_url(request, reverse("core:medication-add") + "?" + query)
