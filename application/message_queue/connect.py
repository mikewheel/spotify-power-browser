import pika
import warnings

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
    # FIXME: maybe better if this were global?
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host='localhost')
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

    result = channel.queue_declare(
        queue=(queue_name if queue_name is not None else ""),
        exclusive=True  # Deletes queue on connection close
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
        body=body
    )
    logger.debug(
        f'Published to exchange {exchange} with routing key {routing_key}'
    )
