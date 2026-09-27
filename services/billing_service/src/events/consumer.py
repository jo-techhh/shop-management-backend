"""
Saga Event Consumer for Billing & POS Service.
Consumes events from stream:inventory (STOCK_RESERVED, STOCK_RESERVATION_FAILED, STOCK_RELEASED)
to transition order states idempotently.
"""
import asyncio
from datetime import datetime, timezone
import logging
from uuid import UUID
import redis.asyncio as aioredis
from sqlalchemy import select

from services.billing_service.src.config import settings
from services.billing_service.src.db.session import AsyncSessionLocal
from services.billing_service.src.models.order import Order
from services.billing_service.src.models.processed import ProcessedEvent
from shared.broker.streams import ack_message, claim_abandoned_messages, ensure_consumer_group, read_from_group, send_to_dlq
from shared.events.base import EventEnvelope, EventType

logger = logging.getLogger("billing_saga_consumer")


async def process_inventory_event(session, event: EventEnvelope) -> None:
    """Process an inventory saga outcome event inside a local ACID transaction."""
    # 1. Idempotency check
    stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event.event_id)
    res = await session.execute(stmt)
    if res.scalar_one_or_none():
        logger.info(f"Inventory event {event.event_id} ({event.event_type}) was already processed. Skipping duplicate.")
        return

    payload = event.payload
    order_id_str = payload.get("order_id", event.aggregate_id)
    order_id = UUID(order_id_str)

    order_res = await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = order_res.scalar_one_or_none()

    if not order:
        logger.warning(f"Order '{order_id}' not found for inventory event {event.event_type}.")
        return

    # 2. Advance Saga Order State Machine
    if event.event_type == EventType.STOCK_RESERVED:
        if order.status == "PENDING":
            order.status = "STOCK_RESERVED"
            logger.info(f"Order {order.id} transitioned PENDING -> STOCK_RESERVED.")

    elif event.event_type == EventType.STOCK_RESERVATION_FAILED:
        if order.status == "PENDING":
            order.status = "STOCK_FAILED"
            logger.warning(f"Order {order.id} transitioned PENDING -> STOCK_FAILED: {payload.get('reason')}")

    elif event.event_type == EventType.STOCK_RELEASED:
        if order.status in ("COMPENSATING_STOCK", "PAYMENT_FAILED", "PENDING"):
            order.status = "CANCELLED"
            logger.info(f"Order {order.id} compensation confirmed -> CANCELLED.")

    # 3. Record in processed_events idempotency table
    processed = ProcessedEvent(
        event_id=event.event_id,
        consumer_name=settings.CONSUMER_NAME,
        aggregate_id=event.aggregate_id,
    )
    session.add(processed)


async def run_inventory_consumer(redis_client: aioredis.Redis, stop_event: asyncio.Event) -> None:
    """Continuous worker loop reading inventory outcome events from Redis Streams."""
    logger.info(f"Billing Saga Consumer starting on stream '{settings.INVENTORY_STREAM}' (group: '{settings.BILLING_CONSUMER_GROUP}').")
    await ensure_consumer_group(redis_client, settings.INVENTORY_STREAM, settings.BILLING_CONSUMER_GROUP)

    # Reclaim unacked messages on startup
    try:
        abandoned = await claim_abandoned_messages(
            redis=redis_client,
            stream=settings.INVENTORY_STREAM,
            group=settings.BILLING_CONSUMER_GROUP,
            consumer=settings.CONSUMER_NAME,
            min_idle_time_ms=30000,
        )
        if abandoned:
            logger.info(f"Reclaimed {len(abandoned)} abandoned messages from {settings.INVENTORY_STREAM}.")
            for msg_id, envelope in abandoned:
                async with AsyncSessionLocal() as session:
                    await process_inventory_event(session, envelope)
                    await session.commit()
                await ack_message(redis_client, settings.INVENTORY_STREAM, settings.BILLING_CONSUMER_GROUP, msg_id)
    except Exception as claim_err:
        logger.warning(f"Could not reclaim abandoned messages on startup: {claim_err}")

    while not stop_event.is_set():
        try:
            messages = await read_from_group(
                redis=redis_client,
                stream=settings.INVENTORY_STREAM,
                group=settings.BILLING_CONSUMER_GROUP,
                consumer=settings.CONSUMER_NAME,
                count=10,
                block_ms=2000,
            )

            if not messages:
                await asyncio.sleep(0.1)
                continue

            for msg_id, envelope in messages:
                try:
                    async with AsyncSessionLocal() as session:
                        await process_inventory_event(session, envelope)
                        await session.commit()

                    await ack_message(redis_client, settings.INVENTORY_STREAM, settings.BILLING_CONSUMER_GROUP, msg_id)

                except Exception as proc_err:
                    logger.error(f"Error processing inventory event {msg_id}: {proc_err}", exc_info=True)
                    await send_to_dlq(
                        redis=redis_client,
                        dlq_stream=settings.DLQ_STREAM,
                        raw_message_id=msg_id,
                        event_data={
                            "event_id": envelope.event_id,
                            "event_type": envelope.event_type.value,
                            "correlation_id": envelope.correlation_id,
                            "payload": envelope.payload,
                        },
                        error_message=str(proc_err),
                        retry_count=1,
                        consumer_name=settings.CONSUMER_NAME,
                    )
                    await ack_message(redis_client, settings.INVENTORY_STREAM, settings.BILLING_CONSUMER_GROUP, msg_id)

        except asyncio.CancelledError:
            logger.info("Billing Saga Consumer received cancellation.")
            break
        except Exception as loop_err:
            logger.error(f"Unexpected error in consumer loop: {loop_err}", exc_info=True)
            await asyncio.sleep(1.0)

    logger.info("Billing Saga Consumer stopped.")
