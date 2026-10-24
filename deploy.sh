#!/bin/bash
# Vitals deploy script. Runs on the server, from the checkout it lives in.
set -e

# The whole body is a function so bash parses the file up front. Without this,
# the `git reset --hard` below can rewrite this very script mid-execution and
# bash resumes reading at a stale byte offset — garbage, on the one deploy that
# actually changes deploy.sh.
main() {
  cd "$(dirname "$0")"

  # Deploy whatever branch the checkout is standing on, not a name baked into
  # this file. A literal here is a trap with no warning attached: point the
  # server at a branch to try something, and the next deploy silently drags it
  # back, leaving a server that reports success and serves the old code.
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$branch" = "HEAD" ]; then
    echo "Detached HEAD — 'git checkout <branch>' before deploying." >&2
    exit 1
  fi

  # GitHub is the source of truth — hard-sync so the deploy target always
  # matches origin, discarding any local drift.
  git fetch origin
  if ! git rev-parse --verify --quiet "origin/$branch" >/dev/null; then
    echo "origin/$branch does not exist — push the branch first." >&2
    exit 1
  fi
  before="$(git rev-parse HEAD)"
  git reset --hard "origin/$branch"

  docker compose up -d --build
  # backup.sh is bind-mounted into vitals_backup as a single file. The reset
  # replaces it with a new inode, and a running container keeps the old one —
  # compose does not recreate a service whose config is unchanged, so the
  # backup loop would go on running the previous script indefinitely.
  if ! git diff --quiet "$before" HEAD -- scripts/backup.sh; then
    docker compose restart vitals_backup
  fi
  # Name the branch on the way out: "it deployed but nothing changed" is almost
  # always this line disagreeing with what you assumed was checked out.
  echo "✓ Vitals deployed — $branch @ $(git rev-parse --short HEAD)"
}

main "$@"
