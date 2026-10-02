#!/usr/bin/env bash
#
# deploy-site.sh — publish the mind-lathe public site's dist/ to the domain root.
#
# Runs on the WORKSTATION (unlike deploy-web.sh, which runs on the box): the
# site is built in the mind-lathe repo, gated here, then rsynced up. Caddy
# serves /srv/mind-lathe at the root (deploy/Caddyfile.hidden), so a content
# swap is just this script — no Caddy change, no reload.
#
#   deploy/bin/deploy-site.sh <path-to-mind-lathe>/dist
#
# The hub-prefix grep is the gate mind-lathe's own gates deliberately can't
# run: that repo must never contain the prefix, even inside a scanner, so only
# this side knows what to look for (mind-lathe NEEDS.md / DECISIONS D3).
set -euo pipefail

DIST="${1:?usage: deploy-site.sh <path-to-dist>}"
HOST="${LIFE_OS_SSH:-vps}"                  # an ~/.ssh/config alias, not an address
# Under /srv, not the deploy user's home: a 0750 home is not traversable by
# the Caddy user (DECISIONS 3 — same reason the hub bundle moved).
DEST="${LIFE_OS_SITE_DIR:-/srv/mind-lathe}"

[ -f "${DIST}/index.html" ] || { echo "!! ${DIST} has no index.html"; exit 1; }

# The prefix's source of truth is the BOX's .env (a workstation .env usually
# doesn't carry it). Read it there unless the caller supplies it. An EMPTY
# prefix must refuse, not pass: `grep -F ""` matches every line, so an empty
# pattern would look like a hit everywhere — or, inverted, prove nothing.
PREFIX="${LIFE_OS_HUB_PREFIX:-$(ssh "${HOST}" "grep -h '^LIFE_OS_HUB_PREFIX=' ~/app/.env | cut -d= -f2-" | tr -d '"' || true)}"
PREFIX="${PREFIX%/}"
[ -n "${PREFIX}" ] && [ "${PREFIX}" != "/" ] || { echo "!! hub prefix unknown — refusing"; exit 1; }
# -F: the prefix is a literal, not a regex. "<prefix>/" and "<prefix>" both
# matched as substrings; "mindlathe" alone can't trip it because the prefix
# carries its leading slash.
if grep -rIlF -- "${PREFIX}" "${DIST}"; then
    echo "!! hub prefix found in the files above — NOT deploying"; exit 1
fi
echo "prefix grep: clean ($(find "${DIST}" -type f | wc -l | tr -d ' ') files)"

# Owned by the deploy user, world-readable, so rsync needs no sudo after this.
ssh "${HOST}" "sudo -n install -d -o \$(id -un) -g \$(id -gn) -m 755 '${DEST}'"
rsync -a --delete --exclude '*.map' "${DIST}/" "${HOST}:${DEST}/"
echo "deployed to ${HOST}:${DEST}"
