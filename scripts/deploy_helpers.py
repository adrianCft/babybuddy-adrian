"""Deployment checks and reversible code installation; never restore a database."""

import argparse
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tarfile

ROOTS = {
    "api",
    "babybuddy",
    "core",
    "dashboard",
    "reports",
    "locale",
    "static",
    "scripts",
}
ROOT_FILES = {"manage.py", "requirements.txt"}


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Ruta insegura en el lanzamiento: " + name)
    return path


def verify_archive(archive):
    with tarfile.open(archive, "r:gz") as bundle:
        roots = set()
        for entry in bundle.getmembers():
            path = safe_relative(entry.name)
            if not path.parts or not (entry.isdir() or entry.isfile()):
                raise ValueError("El paquete contiene enlaces o entradas no permitidas")
            roots.add(path.parts[0])
            name = path.name.lower()
            if (
                name.startswith(("db.sqlite3", ".env"))
                or name == "production.py"
                or name.endswith((".sqlite", ".sqlite3", ".pem", ".key"))
            ):
                raise ValueError("Archivo sensible en el paquete: " + entry.name)
        if len(roots) != 1 or not next(iter(roots)).startswith("babybuddy-adrian-"):
            raise ValueError("El paquete no tiene la estructura esperada")


def asset_manifest(stage):
    root = stage / "static"
    manifest = json.loads((root / "staticfiles.json").read_text(encoding="utf-8"))
    paths = manifest["paths"]
    for required in ("babybuddy/css/app.css", "babybuddy/js/app.js"):
        if required not in paths:
            raise ValueError("Faltan los estáticos compilados: " + required)
    for original, hashed in paths.items():
        for name in (original, hashed):
            path = root.joinpath(*safe_relative(name).parts)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("Estático incompleto: " + name)
            compressed = Path(str(path) + ".gz")
            if (
                compressed.exists()
                and gzip.decompress(compressed.read_bytes()) != path.read_bytes()
            ):
                raise ValueError("Estático comprimido desactualizado: " + name)
    return paths


def destination(app, relative):
    path = app.joinpath(*safe_relative(relative).parts)
    if path.is_symlink() or not path.resolve().is_relative_to(app.resolve()):
        raise ValueError(
            "La instalación intentaría salir del directorio de código: " + relative
        )
    return path


def candidates(stage):
    result = {}
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(stage)
        parts = rel.parts
        if parts[0] not in ROOTS and str(rel) not in ROOT_FILES:
            continue
        if any(
            part
            in {
                "tests",
                "fixtures",
                "static_src",
                "__pycache__",
                ".venv",
                "node_modules",
                ".git",
            }
            for part in parts
        ):
            continue
        if parts[:2] == ("babybuddy", "settings") and parts[-1] not in {
            "base.py",
            "__init__.py",
        }:
            continue
        if path.suffix == ".pyc":
            continue
        result[rel.as_posix()] = path
    # collectstatic needs the app's original files even though Git ships the
    # already collected assets. Copy exactly the original manifest entries.
    for name in asset_manifest(stage):
        if name.startswith("babybuddy/"):
            result["babybuddy/static/" + name] = stage / "static" / name
    return result


def install(stage, app, work):
    files = candidates(stage)
    old_requirements = app / "requirements.txt"
    new_requirements = stage / "requirements.txt"
    if not old_requirements.is_file() or old_requirements.read_bytes().replace(
        b"\r\n", b"\n"
    ) != new_requirements.read_bytes().replace(b"\r\n", b"\n"):
        raise ValueError(
            "Las dependencias han cambiado: revisa el entorno virtual antes de desplegar."
        )
    entries = []
    # Validate every target before changing any code.
    for relative, source in sorted(files.items()):
        target = destination(app, relative)
        if target.exists() and not target.is_file():
            raise ValueError("Destino incompatible: " + str(target))
        if target.is_file() and target.read_bytes() == source.read_bytes():
            continue
        entries.append({"path": relative, "existed": target.exists()})
    work.mkdir(parents=True, exist_ok=True)
    journal = {"entries": entries, "installed": []}
    journal_path = work / "journal.json"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    for entry in entries:
        relative = entry["path"]
        target = destination(app, relative)
        if entry["existed"]:
            backup = work / "files" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        journal["installed"].append(relative)
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[relative], target)
        if not entry["existed"]:
            target.chmod(0o755 if files[relative].stat().st_mode & 0o111 else 0o644)
    app.chmod(0o755)
    print("Código y estáticos instalados; datos y production.py excluidos.")


def rollback(app, work):
    journal_path = work / "journal.json"
    if not journal_path.exists():
        return
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in journal["entries"]}
    for relative in reversed(journal["installed"]):
        target = destination(app, relative)
        if entries[relative]["existed"]:
            shutil.copy2(work / "files" / relative, target)
        elif target.is_file():
            target.unlink()
    print(
        "Restaurado el código anterior. La base de datos no se ha sustituido ni revertido."
    )


def database_snapshot(database, previous=None):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError(
                "La base de datos no supera la comprobación de integridad."
            )
        if previous is None:
            tables = [
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                if row[0].startswith(
                    ("core_", "babybuddy_", "dbsettings_", "auth_user")
                )
                or row[0] == "auth_group"
            ]
            previous = {}
            for table in tables:
                info = db.execute(
                    'PRAGMA table_info("' + table.replace('"', '""') + '")'
                ).fetchall()
                previous[table] = {
                    "columns": [row[1] for row in info],
                    "order": [
                        row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]
                    ],
                }
        result = {}
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        for table, schema in previous.items():
            sql = (
                "SELECT "
                + ",".join(map(quote, schema["columns"]))
                + " FROM "
                + quote(table)
            )
            sql += " ORDER BY " + (",".join(map(quote, schema["order"])) or "rowid")
            digest = hashlib.sha256()
            count = 0
            for row in db.execute(sql):
                digest.update(repr(row).encode("utf-8") + b"\n")
                count += 1
            result[table] = {**schema, "count": count, "sha256": digest.hexdigest()}
        return result


def migration_plan(app, database, settings_module):
    sys.path.insert(0, str(app))
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    import django

    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations import operations as ops

    configured = settings.DATABASES["default"]
    if (
        configured["ENGINE"] != "django.db.backends.sqlite3"
        or Path(configured["NAME"]).resolve() != database.resolve()
    ):
        raise ValueError(
            "La configuración no apunta a la base SQLite esperada. No se ejecutan migraciones."
        )
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    for migration, backwards in plan:
        if backwards:
            raise ValueError("No se permiten migraciones hacia atrás.")
        for operation in migration.operations:
            safe = isinstance(
                operation,
                (
                    ops.CreateModel,
                    ops.AlterModelOptions,
                    ops.AlterModelManagers,
                    ops.AddIndex,
                ),
            )
            safe |= isinstance(operation, ops.AddField) and operation.field.null
            safe |= (
                isinstance(operation, ops.SeparateDatabaseAndState)
                and not operation.database_operations
            )
            if not safe:
                raise ValueError(
                    "Migración que requiere revisión manual antes de publicar: "
                    + migration.app_label
                    + "."
                    + migration.name
                    + " / "
                    + type(operation).__name__
                )
    print(len(plan))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "verify-archive",
            "verify-assets",
            "install",
            "rollback",
            "snapshot",
            "verify-data",
            "plan",
        ],
    )
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    paths = [Path(value) for value in args.paths]
    if args.action == "verify-archive":
        verify_archive(paths[0])
    elif args.action == "verify-assets":
        asset_manifest(paths[0])
    elif args.action == "install":
        install(*paths)
    elif args.action == "rollback":
        rollback(*paths)
    elif args.action == "snapshot":
        paths[1].write_text(json.dumps(database_snapshot(paths[0])), encoding="utf-8")
    elif args.action == "verify-data":
        before = json.loads(paths[1].read_text(encoding="utf-8"))
        if database_snapshot(paths[0], before) != before:
            raise ValueError(
                "Los datos existentes no coinciden con la comprobación anterior. Revisa el despliegue."
            )
        print(
            "Datos existentes verificados: mismos valores, identificadores y relaciones."
        )
    elif args.action == "plan":
        migration_plan(paths[0], paths[1], args.paths[2])


if __name__ == "__main__":
    main()
