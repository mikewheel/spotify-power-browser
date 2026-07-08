---
name: onboard-second-user
description: Add a friend's Spotify library to the shared taste graph — allowlist, OAuth login, migration 0001, per-user crawl, overlap queries. Use when asked to add a user, onboard a friend, set up multiplayer, crawl someone else's library, or compare two users' taste.
---

# Onboard a second user (multiplayer)

Follow **[docs/multiplayer-runbook.md](../../../docs/multiplayer-runbook.md)** —
it is the authoritative step-by-step. Background reading:
[docs/auth.md](../../../docs/auth.md) (primary-user mirror, token layout) and
[docs/data-model.md](../../../docs/data-model.md) (the ownership layer).

The checklist, compressed:

1. **One-time** (if the graph predates multiplayer): run migration 0001 with
   the owner's Spotify user id, then have the owner re-auth via `/login`.
2. **Allowlist the friend** in the Spotify developer dashboard (Settings →
   User Management → their account email) — development-mode apps reject
   everyone else at the consent screen.
3. **Friend logs in** at `http://127.0.0.1:8000/login` → "Add a user" (tunnel
   port 8000 if remote). Their tokens land in `secrets/users/<their_id>/`.
4. **Crawl them**: `CRAWL_USER=<their_id> docker compose up requests_factory_start_crawls`
   (or `CRAWL_ALL_USERS=true` — sequential on purpose; rate limits are per-app).
5. **Explore the overlap**: the query pack tour is in
   [docs/exploring-the-graph.md](../../../docs/exploring-the-graph.md#the-shared-music-space-when-a-friends-library-is-loaded).

Mind the two hard rules: never delete `secrets/users/.primary_user` or the
legacy `secrets/spotify_*.secret` files (they gate compose), and say out loud
that the friend's data lands in the host's Neo4j. Deletion procedure ("right
to be forgotten") is in the runbook §4.
