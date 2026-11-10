#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

APP_DIR="${APP_DIR:-/opt/babybuddy}"
DATA_DIR="${DATA_DIR:-/opt/data}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"
SETTINGS="${SETTINGS:-babybuddy.settings.production}"
RELEASE_FILE="${RELEASE_FILE:-/root/babybuddy-release.env}"
HEALTHCHECK_BASE_URL="${HEALTHCHECK_BASE_URL:-https://acsbaby.duckdns.org}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-0}"

if [ "$#" -eq 2 ]; then
    COMMIT="$1"
    EXPECTED_SHA256="$2"
elif [ "$#" -eq 0 ] && [ -f "$RELEASE_FILE" ]; then
    # shellcheck disable=SC1090
    source "$RELEASE_FILE"
else
    echo "Uso: $0 [commit sha256]; o configura $RELEASE_FILE" >&2
    exit 2
fi
: "${COMMIT:?Falta COMMIT}"
: "${EXPECTED_SHA256:?Falta EXPECTED_SHA256}"
[[ "$COMMIT" =~ ^[0-9a-fA-F]{7,40}$ ]] || { echo "Commit no válido" >&2; exit 2; }
[[ "$EXPECTED_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "SHA256 no válido" >&2; exit 2; }
[[ "$RUN_COLLECTSTATIC" =~ ^[01]$ ]] || { echo "RUN_COLLECTSTATIC debe ser 0 o 1" >&2; exit 2; }

test -d "$APP_DIR"
test -f "$DATA_DIR/db.sqlite3"
test -f "$APP_DIR/babybuddy/settings/production.py"
test -x "$PYTHON"
command -v curl >/dev/null
command -v tar >/dev/null
APP_DIR="$(cd "$APP_DIR" && pwd -P)"
DATA_DIR="$(cd "$DATA_DIR" && pwd -P)"
LOCK_DIR="$APP_DIR/.deploy-lock"
mkdir "$LOCK_DIR" || { echo "Hay otro despliegue o un bloqueo pendiente: $LOCK_DIR" >&2; exit 1; }
TMP=""
SERVICES_STOPPED=0
CODE_CHANGED=0

finish() {
    result=$?
    trap - EXIT
    set +e
    keep=0
    if [ "$result" -ne 0 ] && [ "$CODE_CHANGED" -eq 1 ]; then
        can_restore=1
        if [ "$SERVICES_STOPPED" -eq 0 ]; then
            if systemctl stop uwsgi; then SERVICES_STOPPED=1; else can_restore=0; fi
        fi
        if [ "$can_restore" -eq 1 ]; then
            "$PYTHON" "$HELPER" rollback "$APP_DIR" "$TMP/previous-code" || keep=1
        else
            echo "No se pudo detener uwsgi para restaurar el código. Revisa el servicio." >&2
            SERVICES_STOPPED=1
            keep=1
        fi
    fi
    if [ "$SERVICES_STOPPED" -eq 1 ]; then
        systemctl start uwsgi || { echo "No se ha podido arrancar uwsgi. Revisa su registro." >&2; result=1; }
    fi
    if [ -n "$TMP" ] && [ "$keep" -eq 0 ]; then
        case "$TMP" in /tmp/babybuddy-deploy.*) rm -rf -- "$TMP" ;; *) echo "Temporal fuera de /tmp; no se elimina: $TMP" >&2 ;; esac
    elif [ "$keep" -eq 1 ]; then
        echo "Conservados los archivos de recuperación del código en: $TMP" >&2
    fi
    rmdir -- "$LOCK_DIR"
    exit "$result"
}
trap finish EXIT
TMP="$(mktemp -d /tmp/babybuddy-deploy.XXXXXXXX)"
ARCHIVE="$TMP/release.tar.gz"
STAGE="$TMP/release"
HELPER="$TMP/deploy_helpers.py"
mkdir "$STAGE"
PRODUCTION="$APP_DIR/babybuddy/settings/production.py"
PRODUCTION_BEFORE="$(sha256sum "$PRODUCTION" | awk '{print $1}')"
PRODUCTION_MODE="$(stat -c '%a:%u:%g' "$PRODUCTION")"
DB_INODE="$(stat -c '%d:%i' "$DATA_DIR/db.sqlite3")"
DOWNLOAD_URL="https://github.com/adrianCft/babybuddy-adrian/archive/${COMMIT}.tar.gz"
curl -fsSL --retry 3 --connect-timeout 20 "$DOWNLOAD_URL" -o "$ARCHIVE"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum -c -

# Extract only the helper into a fixed temporary filename, then validate all
# archive paths/types before allowing tar to create any directory or file.
"$PYTHON" - "$ARCHIVE" "$HELPER" <<'PY'
import sys, tarfile
from pathlib import Path
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    entries = [item for item in archive.getmembers() if item.name.endswith('/scripts/deploy_helpers.py')]
    if len(entries) != 1 or not entries[0].isfile() or entries[0].size > 1024 * 1024:
        raise SystemExit('Falta el comprobador de despliegue en este lanzamiento.')
    Path(sys.argv[2]).write_bytes(archive.extractfile(entries[0]).read())
PY
"$PYTHON" "$HELPER" verify-archive "$ARCHIVE"
tar -xzf "$ARCHIVE" --strip-components=1 --no-same-owner --no-same-permissions -C "$STAGE"
"$PYTHON" "$HELPER" verify-assets "$STAGE"
test -f "$STAGE/core/migrations/0043_health_records.py"
test -f "$STAGE/core/health_views.py"

# Keep nginx serving throughout. Set the flag first so a failed stop also
# triggers a start attempt in the EXIT handler.
SERVICES_STOPPED=1
systemctl stop uwsgi
"$PYTHON" "$HELPER" snapshot "$DATA_DIR/db.sqlite3" "$TMP/data-before.json"
CODE_CHANGED=1
"$PYTHON" "$HELPER" install "$STAGE" "$APP_DIR" "$TMP/previous-code"
cd "$APP_DIR"
"$PYTHON" manage.py check --settings="$SETTINGS"
MIGRATIONS="$("$PYTHON" "$HELPER" plan "$APP_DIR" "$DATA_DIR/db.sqlite3" "$SETTINGS")"
[[ "$MIGRATIONS" =~ ^[0-9]+$ ]] || { echo "No se pudo comprobar el plan de migraciones" >&2; exit 1; }
if [ "$MIGRATIONS" -gt 0 ]; then
    "$PYTHON" manage.py migrate --noinput --settings="$SETTINGS"
else
    echo "No hay migraciones pendientes."
fi
if [ "$RUN_COLLECTSTATIC" -eq 1 ]; then
    "$PYTHON" manage.py collectstatic --noinput --settings="$SETTINGS"
fi
"$PYTHON" manage.py check --settings="$SETTINGS"
"$PYTHON" "$HELPER" verify-data "$DATA_DIR/db.sqlite3" "$TMP/data-before.json"
test "$PRODUCTION_BEFORE" = "$(sha256sum "$PRODUCTION" | awk '{print $1}')"
test "$PRODUCTION_MODE" = "$(stat -c '%a:%u:%g' "$PRODUCTION")"
test "$DB_INODE" = "$(stat -c '%d:%i' "$DATA_DIR/db.sqlite3")"
systemctl start uwsgi
SERVICES_STOPPED=0
systemctl is-active --quiet uwsgi
systemctl is-active --quiet nginx

check_http() {
    local url="$1" status
    status="$(curl -sS --retry 2 --retry-connrefused --connect-timeout 5 --max-time 20 -o /dev/null -w '%{http_code}' "$url")"
    case "$status" in
        200|302) echo "$url -> HTTP $status" ;;
        *) echo "$url -> HTTP $status inesperado" >&2; return 1 ;;
    esac
}
check_http "$HEALTHCHECK_BASE_URL/"
check_http "$HEALTHCHECK_BASE_URL/login/"
printf 'COMMIT=%s\nEXPECTED_SHA256=%s\nRUN_COLLECTSTATIC=%s\n' "$COMMIT" "$EXPECTED_SHA256" "$RUN_COLLECTSTATIC" > "$RELEASE_FILE.tmp"
chmod 600 "$RELEASE_FILE.tmp"
mv -f -- "$RELEASE_FILE.tmp" "$RELEASE_FILE"
echo "Despliegue completado: $COMMIT"
