"""Exercise deployment protection using disposable folders, never a real service."""

import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import tarfile
import shutil
from uuid import uuid4
from unittest import TestCase, skipUnless
from django.conf import settings

HELPER = Path(settings.BASE_DIR) / "scripts" / "deploy_helpers.py"
spec = importlib.util.spec_from_file_location("deploy_helpers_under_test", HELPER)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentProtectionTests(TestCase):
    def setUp(self):
        base = Path(tempfile.gettempdir()).resolve()
        self.root = (base / (".deploy-test-" + uuid4().hex[:10])).resolve()
        self.assertEqual(self.root.parent, base)
        self.root.mkdir(mode=0o755)
        self.addCleanup(shutil.rmtree, self.root)
        self.stage = self.root / "stage"
        self.app = self.root / "app"
        self.work = self.root / "previous"
        self.stage.mkdir()
        self.app.mkdir()
        files = {
            "requirements.txt": b"# same dependencies\n",
            "manage.py": b'print("new code")\n',
            "core/health_views.py": b"# new health code\n",
            "core/migrations/0043_health_records.py": b"# migration fixture\n",
            "core/tests/never_copy.py": b"# tests\n",
            "babybuddy/settings/development.py": b"# development only\n",
            "babybuddy/settings/base.py": b"# base settings\n",
            "scripts/deploy_helpers.py": HELPER.read_bytes(),
            "static/babybuddy/css/app.css": b"/* new style */",
            "static/babybuddy/css/app.123.css": b"/* new style */",
            "static/babybuddy/js/app.js": b"// new script",
            "static/babybuddy/js/app.456.js": b"// new script",
        }
        manifest = {
            "version": "1.1",
            "paths": {
                "babybuddy/css/app.css": "babybuddy/css/app.123.css",
                "babybuddy/js/app.js": "babybuddy/js/app.456.js",
            },
        }
        files["static/staticfiles.json"] = json.dumps(manifest).encode()
        for name, content in files.items():
            self.write(self.stage / name, content)
        self.write(self.app / "requirements.txt", files["requirements.txt"])
        self.write(self.app / "manage.py", b'print("old code")\n')
        self.write(
            self.app / "babybuddy/settings/production.py", b"# server configuration\n"
        )
        self.write(self.app / "media/saved-photo.png", b"saved photo bytes")
        self.write(self.app / "data/db.sqlite3", b"saved database sentinel")
        self.write(self.app / ".venv/keep", b"existing virtual environment")

    def write(self, path, content):
        self.assertTrue(path.resolve().is_relative_to(self.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def archive(self, extra=None):
        target = self.root / "release.tar.gz"
        with tarfile.open(target, "w:gz") as bundle:
            for path in sorted(self.stage.rglob("*")):
                if path.is_file():
                    bundle.add(
                        path,
                        arcname="babybuddy-adrian-"
                        + "a" * 40
                        + "/"
                        + path.relative_to(self.stage).as_posix(),
                    )
            if extra:
                member = tarfile.TarInfo(extra)
                member.size = 3
                bundle.addfile(member, io.BytesIO(b"bad"))
        return target

    def test_install_excludes_server_data_and_settings_and_rolls_code_back(self):
        protected = {
            name: (self.app / name).read_bytes()
            for name in [
                "babybuddy/settings/production.py",
                "data/db.sqlite3",
                "media/saved-photo.png",
                ".venv/keep",
            ]
        }
        deploy.verify_archive(self.archive())
        deploy.install(self.stage, self.app, self.work)
        self.assertEqual((self.app / "manage.py").read_bytes(), b'print("new code")\n')
        self.assertTrue((self.app / "babybuddy/static/babybuddy/css/app.css").exists())
        self.assertFalse((self.app / "core/tests").exists())
        self.assertFalse((self.app / "babybuddy/settings/development.py").exists())
        for name, content in protected.items():
            self.assertEqual((self.app / name).read_bytes(), content)
        deploy.rollback(self.app, self.work)
        self.assertEqual((self.app / "manage.py").read_bytes(), b'print("old code")\n')
        for name, content in protected.items():
            self.assertEqual((self.app / name).read_bytes(), content)

    def test_rejects_data_archives_traversal_and_stale_compressed_assets(self):
        for name in [
            "babybuddy-adrian-abc/data/db.sqlite3",
            "babybuddy-adrian-abc/babybuddy/settings/production.py",
            "../outside.txt",
        ]:
            with self.assertRaises(ValueError):
                deploy.verify_archive(self.archive(name))
        self.write(
            self.stage / "static/babybuddy/css/app.css.gz",
            gzip.compress(b"old content"),
        )
        with self.assertRaises(ValueError):
            deploy.asset_manifest(self.stage)

    def test_changed_dependencies_abort_before_code_is_written(self):
        self.write(self.stage / "requirements.txt", b"different dependency\n")
        with self.assertRaises(ValueError):
            deploy.install(self.stage, self.app, self.work)
        self.assertEqual((self.app / "manage.py").read_bytes(), b'print("old code")\n')

    def test_database_verification_detects_changed_values_even_if_counts_match(self):
        database = self.root / "preserved.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE core_records(id INTEGER PRIMARY KEY, notes TEXT)")
            db.execute("INSERT INTO core_records VALUES(1, ?)", ["Original ñ"])
        db.close()
        before = deploy.database_snapshot(database)
        with sqlite3.connect(database) as db:
            db.execute("ALTER TABLE core_records ADD COLUMN optional TEXT NULL")
        db.close()
        self.assertEqual(deploy.database_snapshot(database, before), before)
        with sqlite3.connect(database) as db:
            db.execute("UPDATE core_records SET notes=? WHERE id=1", ["Changed"])
        db.close()
        self.assertNotEqual(deploy.database_snapshot(database, before), before)

    @skipUnless(
        os.environ.get("BABYBUDDY_DEPLOY_SHELL_TEST") == "1",
        "Optional Bash integration test",
    )
    def test_shell_success_failure_and_bad_download_leave_data_and_services_safe(self):
        bash = Path("C:/Program Files/Git/bin/bash.exe")
        python = Path(os.environ["BABYBUDDY_TEST_PYTHON"])
        self.assertTrue(python.is_file())
        self.write(
            self.app / ".venv/bin/python",
            ('#!/bin/bash\nexec "' + python.as_posix() + '" "$@"\n').encode(),
        )
        manage = b'import os,sys\nprint("fixture management check")\nraise SystemExit(1 if os.getenv("FIXTURE_CHECK_FAIL")=="1" else 0)\n'
        self.write(self.stage / "manage.py", manage)
        data = self.root / "persistent"
        data.mkdir()
        database = data / "db.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE core_records(id INTEGER PRIMARY KEY, notes TEXT)")
            db.execute('INSERT INTO core_records VALUES(1, "Preserved")')
        db.close()
        configuration = (
            'SECRET_KEY="fixture"\nINSTALLED_APPS=[]\nDATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":'
            + repr(str(database))
            + "}}\n"
        )
        self.write(self.app / "fixture_settings.py", configuration.encode())
        stubs = self.root / "bin"
        log = self.root / "services.log"
        self.write(
            stubs / "systemctl",
            b'#!/bin/bash\nprintf "%s\\n" "$*" >> "$SERVICE_LOG"\nexit 0\n',
        )
        self.write(
            stubs / "curl",
            b'#!/bin/bash\nout=""\nwhile [ "$#" -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; shift; fi; shift; done\nif [ "$out" = "/dev/null" ]; then printf 200; else cp "$TEST_ARCHIVE" "$out"; fi\n',
        )
        for path in stubs.iterdir():
            path.chmod(0o755)
        (self.app / ".venv/bin/python").chmod(0o755)
        archive = self.archive()
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        original = deploy.database_snapshot(database)
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "APP_DIR": self.app.as_posix(),
            "DATA_DIR": data.as_posix(),
            "PYTHON": (self.app / ".venv/bin/python").as_posix(),
            "SETTINGS": "fixture_settings",
            "RELEASE_FILE": (self.root / "release.env").as_posix(),
            "SERVICE_LOG": log.as_posix(),
            "TEST_ARCHIVE": archive.as_posix(),
            "TEST_STUBS": stubs.as_posix(),
            "RUN_COLLECTSTATIC": "0",
        }
        command = (
            'fixture_bin="$(cygpath -u "$TEST_STUBS")"; export PATH="$fixture_bin:$PATH"; hash -r; test "$(command -v curl)" = "$fixture_bin/curl" && test "$(command -v systemctl)" = "$fixture_bin/systemctl" || exit 99; bash "'
            + (Path(settings.BASE_DIR) / "scripts/deploy-in-container.sh").as_posix()
            + '" '
            + "a" * 40
            + " "
        )
        result = subprocess.run(
            [str(bash), "-lc", command + sha],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(deploy.database_snapshot(database, original), original)
        self.assertNotIn("reload nginx", log.read_text())
        self.assertIn("start uwsgi", log.read_text())
        # A failed check restores the previous code and restarts the app.
        self.write(self.app / "manage.py", b"previous working code\n")
        env["FIXTURE_CHECK_FAIL"] = "1"
        log.write_text("")
        result = subprocess.run(
            [str(bash), "-lc", command + sha],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (self.app / "manage.py").read_bytes(), b"previous working code\n"
        )
        self.assertIn("start uwsgi", log.read_text())
        self.assertEqual(deploy.database_snapshot(database, original), original)
        # A bad download is rejected before stopping any service.
        log.write_text("")
        result = subprocess.run(
            [str(bash), "-lc", command + "0" * 64],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log.read_text(), "")
        self.assertFalse((self.app / ".deploy-lock").exists())
