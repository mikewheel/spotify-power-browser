"""The engine consumer must survive a bad request and reconnect on channel loss.

Regression for the live discography-crawl failure: a non-200/429/500/401 status
raised out of the pika callback under auto_ack, closing the channel; the old
entrypoint then re-called start_consuming() on the *same closed channel*,
hot-spinning "Channel is closed." forever while every subsequent request (the
depth-0 frontier-artist sweep) was published into a torn-down queue.
"""
from unittest.mock import MagicMock

import pytest

import application.api_call_engine as engine
from application.message_queue.connect import bind_queue_to_exchange


def test_named_work_queue_is_durable_and_survives_a_dropped_connection():
    # The make_api_call / response queues are NAMED: they must be durable and
    # NOT exclusive/auto-delete, or one consumer's dropped connection deletes
    # the queue and every request still in it (the discography-crawl failure).
    channel = MagicMock()
    channel.queue_declare.return_value.method.queue = "make_api_call"

    bind_queue_to_exchange(
        channel=channel,
        exchange_name="spotify_api_requests",
        exchange_type="direct",
        routing_key="make_api_call",
        queue_name="make_api_call",
    )

    kwargs = channel.queue_declare.call_args.kwargs
    assert kwargs["durable"] is True
    assert kwargs["exclusive"] is False
    assert kwargs["auto_delete"] is False


def test_unnamed_reply_queue_stays_exclusive():
    channel = MagicMock()
    channel.queue_declare.return_value.method.queue = "amq.gen-xyz"

    bind_queue_to_exchange(
        channel=channel,
        exchange_name="spotify_api_requests",
        exchange_type="direct",
        routing_key="make_api_call",
        queue_name=None,
    )

    kwargs = channel.queue_declare.call_args.kwargs
    assert kwargs["exclusive"] is True
    assert kwargs["durable"] is False


def test_response_worker_entrypoint_reconnects_on_channel_loss(monkeypatch):
    # Same bug as the engine, but in the response workers (write_to_neo4j et al):
    # a closed channel must trigger a RECONNECT, not a hot-spin on the dead one
    # (which froze the durable write_to_neo4j backlog live).
    import application.response_handlers.main as rmain

    connects = []

    def fake_connect(**kwargs):
        connects.append(kwargs)
        channel = MagicMock()
        channel.start_consuming.side_effect = (
            Exception("Channel is closed.") if len(connects) == 1 else SystemExit
        )
        return MagicMock(), channel

    monkeypatch.setattr(rmain, "connect_to_rabbitmq_exchange", fake_connect)
    monkeypatch.setattr(rmain, "bind_queue_to_exchange", lambda **kwargs: "write_to_neo4j")
    monkeypatch.setattr(rmain, "sleep", lambda *_: None)

    with pytest.raises(SystemExit):
        rmain.entrypoint("write_to_neo4j")

    assert len(connects) == 2  # reconnected after the first channel died


def test_response_worker_callback_swallows_a_bad_message(monkeypatch):
    import application.response_handlers.main as rmain

    def boom(ch, method, properties, body):
        raise RuntimeError("neo4j write blip")

    monkeypatch.setattr(rmain.SpotifyResponseController, "_dispatch", staticmethod(boom))
    # Must NOT raise — the worker stays alive for the next message.
    rmain.SpotifyResponseController.dispatch_to_response_parser(None, None, None, b"{}")


def test_bad_request_does_not_propagate_out_of_the_callback(monkeypatch):
    # _consume_request raising (a give-up, or any unexpected error) must be
    # swallowed by the callback, or pika closes the channel under auto_ack.
    boom = []

    def explode(body):
        boom.append(body)
        raise RuntimeError("HTTP 502 received for https://api.spotify.com/...")

    monkeypatch.setattr(engine, "_consume_request", explode)

    # Must NOT raise — the consumer stays alive for the next message.
    engine.make_spotify_api_call(None, None, None, b'{"request_url": "x"}')
    assert boom == [b'{"request_url": "x"}']


def test_entrypoint_reconnects_instead_of_reusing_a_dead_channel(monkeypatch):
    # First start_consuming() fails like a closed channel; the loop must build a
    # NEW connection/channel (reconnect) rather than retry the dead one. The
    # second attempt raises StopIteration to break the otherwise-infinite loop.
    connects = []

    def fake_connect(**kwargs):
        connects.append(kwargs)
        channel = MagicMock()
        if len(connects) == 1:
            # Emulate the closed channel — an Exception the loop must recover from.
            channel.start_consuming.side_effect = Exception("Channel is closed.")
        else:
            # SystemExit is a BaseException (NOT caught by the loop's
            # `except Exception`), so it breaks the otherwise-infinite loop.
            channel.start_consuming.side_effect = SystemExit
        return MagicMock(), channel

    monkeypatch.setattr(engine, "connect_to_rabbitmq_exchange", fake_connect)
    monkeypatch.setattr(engine, "bind_queue_to_exchange", lambda **kwargs: "make_api_call")
    monkeypatch.setattr(engine, "sleep", lambda *_: None)

    with pytest.raises(SystemExit):
        engine.entrypoint()

    # Reconnected: connect_to_rabbitmq_exchange was called a SECOND time after
    # the first channel died (the old code called it exactly once, ever).
    assert len(connects) == 2
