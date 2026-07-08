import pika
import warnings

from application.config import RABBITMQ_HOSTNAME
from application.loggers import get_logger

logger = get_logger(__name__)


def connect_to_rabbitmq_exchange(
        exchange_name,
        exchange_type
):
    """
    Establishes a connection to RabbitMQ at localhost, alongside the channel object with which to manipulate the message
    broker.
    :param exchange_name: the name of the message exchange to create, or to connect to if it exists
    :param exchange_type: the type of exchange to create – or the type that we expect it to be if it exists
    :return: the connection and channel objects as a 2-tuple.
    """
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=RABBITMQ_HOSTNAME,
            # A crawl callback does a (possibly slow) HTTP GET plus a fan-out
            # publish before returning control to pika's I/O loop, which is when
            # heartbeats are serviced. The 60s default let the broker reset the
            # connection under load ("Connection reset by peer"); a long
            # heartbeat tolerates bursty callbacks. Paired with a durable,
            # non-exclusive request queue (below), a reset no longer loses work.
            heartbeat=600,
            blocked_connection_timeout=300,
        )
    )
    channel = connection.channel()

    channel.exchange_declare(
        exchange=exchange_name,
        exchange_type=exchange_type
    )

    return connection, channel


def bind_queue_to_exchange(
        channel,
        exchange_name,
        exchange_type,
        routing_key=None,
        queue_name=None
):
    """
    Establishes a message queue to be associated with a particular exchange.
    :param channel: The object with which to manipulate the message broker.
    :param exchange_name: the name of the exchange to which the queue will be bound
    :param exchange_type: the type of the exchange: direct or fanout are supported.
    :param routing_key: the key with which the exchange will be bound to the queue.
    :param queue_name: the name of the queue, if known; otherwise leave blank for a temporary queue
    :return: the name of the queue as a string
    """

    # A NAMED queue is a shared durable work queue and must NOT be tied to the
    # declaring connection, or one consumer's drop deletes the queue and its
    # backlog (see application/message_queue/README.md). An UNNAMED queue is a
    # throwaway reply queue and stays exclusive/auto-deleting.
    is_named = queue_name is not None
    result = channel.queue_declare(
        queue=(queue_name if is_named else ""),
        durable=is_named,          # survive a broker restart
        exclusive=not is_named,    # not bound to one connection
        auto_delete=not is_named,  # not deleted when the last consumer drops
    )

    queue_name = result.method.queue

    if exchange_type == "direct":
        if routing_key is None:
            raise ValueError('Routing key cannot be None for an exchange of type "direct".')

        logger.info(f'Binding queue "{queue_name}" to exchange "{exchange_name}" with routing key "{routing_key}"')
        channel.queue_bind(
            exchange=exchange_name,
            queue=queue_name,
            routing_key=routing_key
        )

    elif exchange_type == "fanout":
        if routing_key is not None:
            warnings.warn(
                f'The routing key "{routing_key}" is going to be ignored since the exchange type is "fanout".'
            )

        logger.info(f'Binding queue "{queue_name}" to exchange "{exchange_name}" with routing key "{routing_key}"')
        channel.queue_bind(
            exchange=exchange_name,
            queue=queue_name,
            routing_key=None
        )

    else:
        raise NotImplementedError(f"Unable to bind queue to exchange {exchange_name} of type {exchange_type}")

    return queue_name


def publish_message_to_exchange(channel, exchange, routing_key, body):
    channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=body,
        # Persist messages so queued work survives a broker restart (the durable
        # queues above only persist the queue, not its transient messages).
        properties=pika.BasicProperties(delivery_mode=2),
    )
    logger.debug(
        f'Published to exchange {exchange} with routing key {routing_key}'
    )
