# cache/ — Redis client (crawl memory + login nonces)

One module, [redis_client.py](redis_client.py), two unrelated jobs that both
happen to need Redis:

**1. Crawled-URL dedup** — the reason a 12k-track library doesn't become a
million requests. Every outbound URL is `SADD`ed to a set *at publish time*
(so two workers queuing the same URL in the same second collapse to one
fetch); members are keyed `"{depth}|{url}"` so a URL seen at depth 0 can
still be re-fetched later at a deeper depth. Two sets exist:

- `spb:crawled_urls` — the shared catalog (tracks/albums/artists are the same
  for everyone)
- `spb:crawled_urls:<user_id>` — per-user, for `/v1/me/*` URLs (your Liked
  Songs page 2 is not your friend's)

`unmark_url()` is the rollback used when a fetch permanently fails — without
it a failed URL would be remembered as "done" and silently lost.
`RESET_CRAWL` / `RESET_CRAWL_CATALOG` clear the user set / shared set
respectively. The set survives restarts (Redis AOF + named volume) — that
persistence is a feature, not an accident.

**2. OAuth state nonces** — `store_oauth_state()` / `consume_oauth_state()`
(atomic `GETDEL`, 10-minute TTL) back the login flow's CSRF protection. See
[docs/auth.md](../../docs/auth.md).
