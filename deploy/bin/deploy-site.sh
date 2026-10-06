#!/usr/bin/env bash
#
# deploy-site.sh — publish a static dist/ to the box (by default mind-lathe's, at
# the domain root; LIFE_OS_SITE_DIR picks another directory, e.g. Endless Trance's).
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

# ONE TCP connection for the whole deploy. The box's firewall is `ufw limit 22/tcp`
# (deploy/bootstrap.sh): an address opening 6+ SSH connections in 30 s is refused
# ("Connection refused"). This script used to open three (prefix, mkdir, rsync),
# so two deploys close together tripped it (2026-10-04). OpenSSH multiplexing
# runs every step over the first connection. The socket lives in a private temp
# dir (macOS caps socket paths near 104 chars; $TMPDIR stays well under).
CTLDIR="$(mktemp -d)"; CTL="${CTLDIR}/cm"
SSHO=(-o ControlMaster=auto -o "ControlPath=${CTL}")
cleanup() { ssh -o "ControlPath=${CTL}" -O exit "${HOST}" >/dev/null 2>&1 || true; rm -rf "${CTLDIR}"; }
trap cleanup EXIT
trap 'echo "!! deploy failed. If ssh said \"Connection refused\", that is the firewall rate limit (6 SSH connections per 30 s): wait half a minute and rerun." >&2' ERR
# Open the shared connection up front, on its own (-f: background after auth,
# -N: no command). Opening it lazily inside the $(...) below can hang: the
# backgrounded master would inherit, and hold open, the substitution's pipe.
ssh "${SSHO[@]}" -fN "${HOST}"

# The prefix's source of truth is the BOX's .env (a workstation .env usually
# doesn't carry it). Read it there unless the caller supplies it. An EMPTY
# prefix must refuse, not pass: `grep -F ""` matches every line, so an empty
# pattern would look like a hit everywhere — or, inverted, prove nothing.
PREFIX="${LIFE_OS_HUB_PREFIX:-$(ssh "${SSHO[@]}" "${HOST}" "grep -h '^LIFE_OS_HUB_PREFIX=' ~/app/.env | cut -d= -f2-" | tr -d '"' || true)}"
PREFIX="${PREFIX%/}"
[ -n "${PREFIX}" ] && [ "${PREFIX}" != "/" ] || { echo "!! hub prefix unknown (could not read it from the box?) — refusing"; exit 1; }
# -F: the prefix is a literal, not a regex. "<prefix>/" and "<prefix>" both
# matched as substrings; "mindlathe" alone can't trip it because the prefix
# carries its leading slash.
if grep -rIlF -- "${PREFIX}" "${DIST}"; then
    echo "!! hub prefix found in the files above — NOT deploying"; exit 1
fi
echo "prefix grep: clean ($(find "${DIST}" -type f | wc -l | tr -d ' ') files)"

# Owned by the deploy user, world-readable, so rsync needs no sudo after this.
ssh "${SSHO[@]}" "${HOST}" "sudo -n install -d -o \$(id -un) -g \$(id -gn) -m 755 '${DEST}'"
rsync -a --delete --exclude '*.map' -e "ssh ${SSHO[*]}" "${DIST}/" "${HOST}:${DEST}/"
# rsync -a copies local permissions, and a build that writes its file 0600
# (Endless Trance's does) would land unreadable to the Caddy user: a 403 for
# every visitor. Published files are world-readable by definition, so fix them
# on the box. Not rsync's --chmod: macOS ships openrsync, which rejects it.
# Runs over the shared connection, so it costs no extra SSH connection.
ssh "${SSHO[@]}" "${HOST}" "chmod -R u=rwX,go=rX '${DEST}'"
echo "deployed to ${HOST}:${DEST}"
