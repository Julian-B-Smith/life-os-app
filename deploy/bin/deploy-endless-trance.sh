#!/usr/bin/env bash
#
# deploy-endless-trance.sh — publish Endless Trance at mindlathe.xyz/endless-trance/.
#
# Runs on the WORKSTATION. Takes the page Endless Trance's own build writes,
# adapts it for the domain (deploy/sites/endless-trance/adapt.py: fonts inline,
# no outside requests), and publishes it as /srv/endless-trance/index.html
# through deploy-site.sh, which runs the hub-prefix grep and uploads over one
# SSH connection. Caddy serves that directory at /endless-trance/
# (deploy/Caddyfile.hidden).
#
#   python3 <endless-trance>/tools/build_av.py        # in Endless Trance, first
#   deploy/bin/deploy-endless-trance.sh <endless-trance>/dist/endless-trance-av.html
set -euo pipefail

SRC="${1:?usage: deploy-endless-trance.sh <path-to>/dist/endless-trance-av.html}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
[ -f "${SRC}" ] || { echo "!! ${SRC} not found — run Endless Trance's tools/build_av.py first"; exit 1; }

OUT="$(mktemp -d)"; trap 'rm -rf "${OUT}"' EXIT
python3 "${HERE}/deploy/sites/endless-trance/adapt.py" "${SRC}" "${OUT}/index.html"
LIFE_OS_SITE_DIR=/srv/endless-trance "${HERE}/deploy/bin/deploy-site.sh" "${OUT}"
