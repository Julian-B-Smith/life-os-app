#!/usr/bin/env bash
#
# caddy-apply.sh — render the tracked Caddyfile, SHOW the diff against the live
# one, validate it, and only install + reload with --apply. Runs on the box.
#
#   bash deploy/bin/caddy-apply.sh            # dry run: diff + validate
#   bash deploy/bin/caddy-apply.sh --apply    # then install + reload
#
# Why not just re-run install-services.sh: it overwrites /etc/caddy/Caddyfile
# blind, and the live file has been hand-edited before (DECISIONS 3 moved the
# hub bundle to /srv while the template still names /home/life/web). A blind
# overwrite would silently revert that. Read the diff; if it shows a live edit
# the template lacks, fix the TEMPLATE first, then apply.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOMAIN="${DOMAIN:-mindlathe.xyz}"
LIVE=/etc/caddy/Caddyfile
NEW="$(mktemp)"
trap 'rm -f "$NEW"' EXIT

PREFIX=$(grep -E '^LIFE_OS_HUB_PREFIX=' "${APP_DIR}/.env" | head -1 | cut -d= -f2- \
    | tr -d "\"'" | sed 's:/*$::')
[ -n "${PREFIX}" ] || { echo "!! no LIFE_OS_HUB_PREFIX in .env — this script is for hidden mode"; exit 1; }
sed -e "s/__DOMAIN__/${DOMAIN}/g" -e "s|__HUB_PREFIX__|${PREFIX}|g" \
    "${APP_DIR}/deploy/Caddyfile.hidden" > "${NEW}"

echo "==> diff live → new:"
diff -u "${LIVE}" "${NEW}" && { echo "(no change)"; exit 0; } || true
echo "==> validate:"
sudo caddy validate --adapter caddyfile --config "${NEW}"

if [ "${1:-}" = "--apply" ]; then
    sudo cp "${LIVE}" "${LIVE}.bak-$(date +%Y%m%d%H%M%S)"
    sudo install -m 644 "${NEW}" "${LIVE}"
    sudo systemctl reload caddy
    echo "==> applied; previous config kept as ${LIVE}.bak-*"
else
    echo "==> dry run only. Re-run with --apply to install + reload."
fi
