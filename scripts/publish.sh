#!/usr/bin/env bash
# Fetch the latest Facebook and Instagram posts, rebuild the wall, push to Pages.
# Silent on success (safe for a no_agent cron job), loud on failure.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

if [[ ! -f .env ]]; then
  # Not configured yet: nothing to say, exit quietly.
  exit 0
fi

log() { printf '%s\n' "$*"; }

if ! out=$(python3 scripts/fetch_feed.py 2>&1); then
  log "RocMaidan feed: fetch failed"
  log "$out" | tail -5
  exit 0
fi

if ! out=$(python3 scripts/build_site.py 2>&1); then
  log "RocMaidan feed: build failed"
  log "$out" | tail -5
  exit 0
fi

if command -v python3 >/dev/null && [[ -x /usr/bin/chromium ]]; then
  if ! out=$(python3 scripts/verify_layout.py --width 1280 2>&1); then
    log "RocMaidan feed: layout check failed, NOT publishing"
    log "$out" | tail -8
    exit 0
  fi
fi

git add -A
if git diff --cached --quiet; then
  exit 0
fi
if ! out=$(git -c user.name="rocmaidan-feed bot" -c user.email="bot@users.noreply.github.com" \
           commit -m "feed: refresh $(date -u +%Y-%m-%dT%H:%MZ)" 2>&1); then
  log "RocMaidan feed: commit failed"; log "$out" | tail -5; exit 0
fi
if ! out=$(git push origin HEAD:main 2>&1); then
  log "RocMaidan feed: push failed"; log "$out" | tail -5; exit 0
fi
exit 0