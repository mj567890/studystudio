"""
apps/api/core/events.py
RabbitMQ 事件总线 —— 基于 aio-pika 的异步 pub/sub 封装

与 Celery 共用同一 RabbitMQ 实例，连接池独立，互不干扰。
提供幂等消费保障（event_idempotency 表）和死信队列（DLQ）支持。
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import aio_pika
import structlog
from sqlalchemy import text

from apps.api.core.config import CONFIG

logger = structlog.get_logger(__name__)


class EventBus:
    """异步事件总线，负责事件发布与订阅。"""

    def __init__(self) -> None:
        self._connection: aio_pika.abc.AbstractConnection | None = None
        self._channel:    aio_pika.abc.AbstractChannel    | None = None
        self._exchange:   aio_pika.abc.AbstractExchange   | None = None
        self._handlers:   dict[str, list[Callable]]       = {}

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(CONFIG.rabbitmq.url)
        self._channel    = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=10)
        # 主交换机：topic 类型，支持通配符路由
        self._exchange = await self._channel.declare_exchange(
            "adaptive_learning",
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        logger.info("EventBus connected to RabbitMQ")

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()

    async def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        """发布事件到交换机。"""
        if self._exchange is None:
            raise RuntimeError("EventBus not connected")

        envelope = {
            "event_id":      str(uuid.uuid4()),
            "event_name":    event_name,
            "event_version": "v1",
            "event_time":    datetime.now(timezone.utc).isoformat(),
            "producer":      "adaptive-learning-api",
            "trace_id":      str(uuid.uuid4()),
            "payload":       payload,
        }

        message = aio_pika.Message(
            body=json.dumps(envelope, ensure_ascii=False).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=envelope["event_id"],
        )

        await self._exchange.publish(message, routing_key=event_name)
        logger.debug("Event published", event_name=event_name, event_id=envelope["event_id"])

    async def subscribe(
        self,
        event_name: str,
        queue_name: str,
        handler: Callable[[dict], Awaitable[None]],
        *,
        db_session_factory=None,
    ) -> None:
        """
        订阅事件。handler 接收完整 envelope dict。
        支持幂等消费：消费前查 event_idempotency 表，已处理则跳过。
        """
        if self._channel is None:
            raise RuntimeError("EventBus not connected")

        # 声明队列（持久化 + 死信队列绑定）
        dlq_name = f"{queue_name}.dlq"
        dlq = await self._channel.declare_queue(dlq_name, durable=True)
        queue = await self._channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": dlq_name,
                "x-message-ttl": 86_400_000,  # 24h
            }
        )
        await queue.bind(self._exchange, routing_key=event_name)

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            async with message.process(requeue=True):
                try:
                    envelope = json.loads(message.body)
                    event_id  = envelope["event_id"]
                    consumer_id = queue_name

                    # 幂等检查
                    if db_session_factory:
                        async with db_session_factory() as session:
                            result = await session.execute(
                                text("SELECT 1 FROM event_idempotency WHERE consumer_id=:c AND event_id=:e"),
                                {"c": consumer_id, "e": event_id}
                            )
                            if result.fetchone():
                                logger.debug("Duplicate event skipped", event_id=event_id)
                                return
                            await session.execute(
                                text("INSERT INTO event_idempotency(consumer_id, event_id, processed_at) "
                                     "VALUES(:c, :e, NOW()) ON CONFLICT DO NOTHING"),
                                {"c": consumer_id, "e": event_id}
                            )
                            await session.commit()

                    await handler(envelope)

                except Exception as exc:
                    logger.error("Event handler failed", error=str(exc), exc_info=True)
                    raise  # 触发 nack → 死信队列

        await queue.consume(_on_message)
        logger.info("Subscribed to event", event_name=event_name, queue=queue_name)


# 全局单例
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
