#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/babybuddy}"
DATA_DIR="${DATA_DIR:-/opt/data}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"
SETTINGS="${SETTINGS:-babybuddy.settings.production}"
RELEASE_FILE="${RELEASE_FILE:-/root/babybuddy-release.env}"
HEALTHCHECK_BASE_URL="${HEALTHCHECK_BASE_URL:-https://acsbaby.duckdns.org}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-0}"

if [ ! -f "$RELEASE_FILE" ]; then
    echo "Falta el archivo de lanzamiento: $RELEASE_FILE" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$RELEASE_FILE"
: "${COMMIT:?COMMIT no está definido en $RELEASE_FILE}"
: "${EXPECTED_SHA256:?EXPECTED_SHA256 no está definido en $RELEASE_FILE}"

ARCHIVE_ROOT="babybuddy-adrian-${COMMIT}"
DOWNLOAD_URL="https://github.com/adrianCft/babybuddy-adrian/archive/${COMMIT}.tar.gz"
ARCHIVE="$(mktemp "/tmp/babybuddy-${COMMIT}.XXXXXX.tar.gz")"
STAGE="$(mktemp -d "/tmp/babybuddy-${COMMIT}.XXXXXX")"
SERVICES_STOPPED=0

finish() {
    result=$?
    trap - EXIT
    set +e
    if [ "$SERVICES_STOPPED" -eq 1 ]; then
        systemctl start uwsgi
    fi
    systemctl reload nginx || systemctl restart nginx
    rm -f -- "$ARCHIVE"
    rm -rf -- "$STAGE"
    exit "$result"
}
trap finish EXIT

test -f "$DATA_DIR/db.sqlite3"
test -f "$APP_DIR/babybuddy/settings/production.py"
test -x "$PYTHON"
command -v curl >/dev/null 2>&1

PRODUCTION_SHA_BEFORE="$(sha256sum "$APP_DIR/babybuddy/settings/production.py" | awk '{print $1}')"
DB_INODE_BEFORE="$(stat -c '%d:%i' "$DATA_DIR/db.sqlite3")"

curl -fsSL --retry 3 --connect-timeout 20 "$DOWNLOAD_URL" -o "$ARCHIVE"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum -c -

tar -xzf "$ARCHIVE" --strip-components=1 -C "$STAGE"

SENSITIVE_FILE="$(find "$STAGE" -type f \
    \( -name 'db.sqlite3' -o -name 'production.py' -o -name '.env' -o -name '.env.*' \) \
    -print -quit)"
if [ -n "$SENSITIVE_FILE" ]; then
    echo "El tar contiene un archivo sensible inesperado: $SENSITIVE_FILE" >&2
    exit 1
fi

for config in development.py ci.py clever-cloud.py test.py production.example.py; do
    rm -f -- "$STAGE/babybuddy/settings/$config"
done

test -f "$STAGE/core/migrations/0043_health_records.py"
test -f "$STAGE/core/health_views.py"
test -d "$STAGE/core/templates/core/health"

systemctl stop uwsgi
SERVICES_STOPPED=1

# The archive contains only repository files. Local data and production.py are
# outside the archive and are deliberately left in place.
cp -a "$STAGE/." "$APP_DIR/"

cd "$APP_DIR"
"$PYTHON" manage.py migrate --noinput --settings="$SETTINGS"
"$PYTHON" manage.py check --settings="$SETTINGS"

if [ "$RUN_COLLECTSTATIC" = "1" ]; then
    "$PYTHON" manage.py collectstatic --noinput --settings="$SETTINGS"
fi

PRODUCTION_SHA_AFTER="$(sha256sum "$APP_DIR/babybuddy/settings/production.py" | awk '{print $1}')"
DB_INODE_AFTER="$(stat -c '%d:%i' "$DATA_DIR/db.sqlite3")"
test "$PRODUCTION_SHA_BEFORE" = "$PRODUCTION_SHA_AFTER"
test "$DB_INODE_BEFORE" = "$DB_INODE_AFTER"

systemctl start uwsgi
SERVICES_STOPPED=0
systemctl is-active --quiet uwsgi
systemctl reload nginx || systemctl restart nginx
systemctl is-active --quiet nginx

check_http() {
    local url="$1"
    local status
    status="$(curl -k -sS --max-time 20 -o /dev/null -w '%{http_code}' "$url")"
    case "$status" in
        200|302) echo "$url -> HTTP $status" ;;
        *) echo "$url -> HTTP $status inesperado" >&2; return 1 ;;
    esac
}

check_http "$HEALTHCHECK_BASE_URL/"
check_http "$HEALTHCHECK_BASE_URL/login/"
echo "Despliegue completado: $COMMIT"
