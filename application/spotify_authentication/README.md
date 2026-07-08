# spotify_authentication/ — OAuth login and token care

The self-contained identity component: a small Falcon web app that turns a
Spotify consent click into token files, plus the code that keeps those tokens
fresh. **The full story — flow diagram, file layout, scopes, the primary-user
mirror, extraction-as-a-library notes — is in [docs/auth.md](../../docs/auth.md).**

| File | Job |
|---|---|
| [api_authorization_web_service.py](api_authorization_web_service.py) | Serves `/login` (user list + "add a user"), `/login/start` (mints a single-use CSRF nonce into Redis, redirects to Spotify), `/callback` (validates the nonce, exchanges the code, asks `/v1/me` whose token it is, saves) |
| [token_store.py](token_store.py) | All reads/writes of token files. Multi-user: `secrets/users/<id>/`; the first user to log in becomes the sticky **primary** and is mirrored to the legacy `secrets/spotify_*.secret` files (the compose healthcheck gate reads those) |
| [refresh_token.py](refresh_token.py) | POSTs the refresh token with HTTP Basic client auth (required — omitting it was the ~1-hour crawl-death bug, PR #16); keeps primary/legacy copies in sync both directions |

Consumed by exactly three production modules (`api_call_engine`,
`playlists/sync`, `response_handlers/me/my_liked_songs`) — see
[docs/auth.md](../../docs/auth.md#where-auth-touches-the-rest-of-the-codebase).

Tests: `test_oauth_service.py`, `test_token_store.py`, `test_refresh_token.py`.
