#!/usr/bin/env bash
#
# deploy-endless-chiptunes.sh — publish Endless Chiptunes at mindlathe.xyz/endless-chiptunes/.
#
# Runs on the WORKSTATION. Takes the project's own site build, adapts it for the
# domain (deploy/sites/endless-chiptunes/adapt.py: fonts inline, no outside
# requests), and publishes it as /srv/endless-chiptunes/index.html through
# deploy-site.sh (hub-prefix grep, one SSH connection, world-readable files).
# Caddy serves that directory at /endless-chiptunes/ (deploy/Caddyfile.hidden).
#
#   python3 <endless-chiptunes>/tools/build_av.py --site      # in Endless Chiptunes, first
#   deploy/bin/deploy-endless-chiptunes.sh <endless-chiptunes>/dist/endless-chiptunes-site.html
#
# The --site build, not the artifact build: it hides export (window.EC_EXPORT=false).
set -euo pipefail

SRC="${1:?usage: deploy-endless-chiptunes.sh <path-to>/dist/endless-chiptunes-site.html}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
[ -f "${SRC}" ] || { echo "!! ${SRC} not found — run Endless Chiptunes' tools/build_av.py --site first"; exit 1; }
case "${SRC}" in *-site.html) ;; *) echo "!! expected the --site build (*-site.html); the artifact build shows export"; exit 1;; esac

OUT="$(mktemp -d)"; trap 'rm -rf "${OUT}"' EXIT
python3 "${HERE}/deploy/sites/endless-chiptunes/adapt.py" "${SRC}" "${OUT}/index.html"
LIFE_OS_SITE_DIR=/srv/endless-chiptunes "${HERE}/deploy/bin/deploy-site.sh" "${OUT}"
