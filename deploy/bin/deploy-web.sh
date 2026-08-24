#!/usr/bin/env bash
#
# deploy-web.sh — publish the life-os-web static bundle to the VPS.
#
# The React hub is a SEPARATE build artifact from this Python app: it is built
# on a workstation and copied here as plain files. No Node runtime on the box,
# and deliberately NOT wired into the app's pytest deploy gate — a frontend
# build must never be able to block a backend deploy (or vice versa).
#
# Usage (from the life-os-web checkout, after `npm run build`):
#   deploy/bin/deploy-web.sh <path-to-dist>
#
# Source maps are excluded on purpose: they would publish readable sources at an
# unauthenticated path. The bundle is served without auth (normal for a SPA —
# all DATA sits behind /api/*), so the less it reveals, the better.
set -euo pipefail

DIST="${1:?usage: deploy-web.sh <path-to-dist>}"
DEST="${LIFE_OS_WEB_DIR:-/home/life/web}"

[ -f "${DIST}/index.html" ] || { echo "!! ${DIST} has no index.html"; exit 1; }

mkdir -p "${DEST}"
# --delete so a removed asset does not linger; sourcemaps filtered out.
rsync -a --delete --exclude '*.map' "${DIST}/" "${DEST}/"
echo "deployed $(find "${DEST}" -type f | wc -l | tr -d ' ') files to ${DEST}"
