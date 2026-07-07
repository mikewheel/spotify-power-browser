#!/usr/bin/env bash
#
# Per-worktree Docker Compose isolation.
#
# The whole project shares ONE image tag (spotify-power-browser:latest) and ONE
# compose project name (spotify-power-browser). On a single Docker daemon that
# means parallel Claude Code worktrees collide: a `docker compose build` in one
# clobbers the shared :latest another is about to `run --rm tests` against, and
# `run`/`up` share containers, networks, and the redis/mock state the tests
# mutate.
#
# This gives each *Claude worktree* its own image tag + compose project by
# writing IMAGE_TAG and COMPOSE_PROJECT_NAME into the worktree's gitignored
# .env (compose auto-loads it). It is a deliberate NO-OP outside
# .claude/worktrees/*, so the PRIMARY checkout keeps the shared defaults, its
# `:latest`, and its warm redis_data volume. Live crawls (the real host Neo4j
# graph + warm dedup) stay singular/serial there.
#
# Wired as a SessionStart hook in .claude/settings.json; safe to run by hand.
set -euo pipefail

root="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$root" ]; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
[ -n "$root" ] || exit 0

# Only isolate ephemeral Claude worktrees; never touch the primary checkout.
case "$root" in
    */.claude/worktrees/*) ;;
    *) exit 0 ;;
esac

branch="$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached)"
# Sanitize to a valid Docker tag / compose project name: lowercase, and every
# character outside [a-z0-9_-] (notably the '/' in claude/xxx) becomes '-';
# then trim to a leading alphanumeric and no trailing dash.
slug="$(printf '%s' "$branch" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9_-]/-/g' -e 's/^[^a-z0-9]*//' -e 's/-*$//')"
[ -n "$slug" ] || slug="worktree"

env_file="$root/.env"
tag="$slug"
project="spotify-power-browser-$slug"

# Idempotent upsert of just our keys; preserve any other .env lines the user
# set (RESET_CRAWL, USE_BATCH_ENDPOINTS, ...). The *_PORT_MAP values are the
# bare container port, so Docker publishes them on a RANDOM free host port —
# isolated worktree stacks never fight over 5672/15672/8000 (the primary keeps
# the fixed localhost mappings via the compose defaults).
touch "$env_file"
tmp="$(mktemp "${TMPDIR:-/tmp}/spb-env.XXXXXX")"
grep -vE '^(IMAGE_TAG|COMPOSE_PROJECT_NAME|RABBITMQ_AMQP_PORT_MAP|RABBITMQ_MGMT_PORT_MAP|AUTH_PORT_MAP)=' "$env_file" > "$tmp" || true
{
    echo "IMAGE_TAG=$tag"
    echo "COMPOSE_PROJECT_NAME=$project"
    echo "RABBITMQ_AMQP_PORT_MAP=5672"
    echo "RABBITMQ_MGMT_PORT_MAP=15672"
    echo "AUTH_PORT_MAP=8000"
} >> "$tmp"
mv "$tmp" "$env_file"

echo "[compose-isolation] worktree '$branch' -> image spotify-power-browser:$tag, compose project $project (host ports randomized)"
