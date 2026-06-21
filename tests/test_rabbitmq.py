from application.message_queue.connect import bind_queue_to_exchange
from application.message_queue.constants import RequestsExchange


def test_connect_declare_exchange_and_bind_queue(rabbitmq_channel):
    # rabbitmq_channel skips the test if RabbitMQ isn't reachable.
    queue_name = bind_queue_to_exchange(
        rabbitmq_channel,
        RequestsExchange.EXCHANGE_NAME.value,
        RequestsExchange.EXCHANGE_TYPE.value,
        routing_key="test_routing_key",
        queue_name="test_queue",
    )
    assert queue_name == "test_queue"
