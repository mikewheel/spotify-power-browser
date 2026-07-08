# message_queue/ — RabbitMQ plumbing

Thin helpers over [pika](https://pika.readthedocs.io/), shared by every
service that touches the broker.

- [constants.py](constants.py) — the topology, in one place: the
  `spotify_api_requests` exchange (routing key `make_api_call`) and the
  `spotify_api_responses` exchange (routing keys `write_to_disk`,
  `write_to_neo4j`, `follow_links`, plus the unused `write_to_sqlite`). Both
  are `direct` exchanges.
- [connect.py](connect.py) — connect (600 s heartbeat, tuned so a slow
  fetch-and-fan-out callback doesn't get the connection reaped), declare
  exchanges, bind queues, publish persistent messages.

The one hard-won rule encoded here: **work queues are named, durable, and
non-exclusive.** An exclusive/auto-delete queue vanishes when its consumer
disconnects — which once silently discarded ~950 queued requests when the
engine reconnected mid-crawl (fixed in PR #26, regression-tested in
`tests/test_engine_consumer_resilience.py`).
