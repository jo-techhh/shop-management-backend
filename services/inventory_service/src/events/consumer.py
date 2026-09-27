"""
Saga Event Consumer for Catalog & Inventory Service.
Consumes events from stream:orders (ORDER_CREATED, ORDER_CANCELLED, ORDER_PAID)
with strict consumer idempotency and row-level locking.
"""
import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional
from uuid import UUID
import redis.asyncio as aioredis
from sqlalchemy import select

from services.inventory_service.src.config import settings
from services.inventory_service.src.db.session import AsyncSessionLocal
from services.inventory_service.src.models.processed import ProcessedEvent
from services.inventory_service.src.services import stock_service
from shared.broker.streams import ack_message, claim_abandoned_messages, ensure_consumer_group, read_from_group, send_to_dlq
from shared.events.base import EventEnvelope, EventType

logger = logging.getLogger("inventory_saga_consumer")


async def process_order_event(session, event: EventEnvelope) -> None:
    """Process a single order event idempotently inside a local ACID transaction."""
    # 1. Idempotency check: Has this event already been processed?
    stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event.event_id)
    res = await session.execute(stmt)
    if res.scalar_one_or_none():
        logger.info(f"Event {event.event_id} ({event.event_type}) was already processed. Skipping duplicate.")
        return

    payload = event.payload
    order_id = payload.get("order_id", event.aggregate_id)
    outlet_id = UUID(payload["outlet_id"])
    items = payload.get("items", [])

    # 2. Dispatch based on event type
    if event.event_type == EventType.ORDER_CREATED:
        await stock_service.reserve_stock_for_order(
            session=session,
            order_id=order_id,
            outlet_id=outlet_id,
            items=items,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
        )

    elif event.event_type in (EventType.ORDER_CANCELLED, EventType.PAYMENT_FAILED):
        reason = payload.get("reason", "Cancelled / Payment failure")
        await stock_service.release_stock_for_order(
            session=session,
            order_id=order_id,
            outlet_id=outlet_id,
            items=items,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            reason=reason,
        )

    elif event.event_type == EventType.ORDER_PAID:
        await stock_service.deduct_stock_for_order(
            session=session,
            order_id=order_id,
            outlet_id=outlet_id,
            items=items,
            reference_id=order_id,
        )
    else:
        logger.debug(f"Inventory consumer ignoring unhandled event type: {event.event_type}")

    # 3. Record event in idempotency table
    processed = ProcessedEvent(
        event_id=event.event_id,
        consumer_name=settings.CONSUMER_NAME,
        aggregate_id=event.aggregate_id,
    )
    session.add(processed)


async def run_order_consumer(redis_client: aioredis.Redis, stop_event: asyncio.Event) -> None:
    """Continuous worker loop reading order events from Redis Streams."""
    logger.info(f"Inventory Saga Consumer starting on stream '{settings.ORDERS_STREAM}' (group: '{settings.INVENTORY_CONSUMER_GROUP}').")
    await ensure_consumer_group(redis_client, settings.ORDERS_STREAM, settings.INVENTORY_CONSUMER_GROUP)

    # Reclaim any unacked messages from previously crashed instances
    try:
        abandoned = await claim_abandoned_messages(
            redis=redis_client,
            stream=settings.ORDERS_STREAM,
            group=settings.INVENTORY_CONSUMER_GROUP,
            consumer=settings.CONSUMER_NAME,
            min_idle_time_ms=30000,
        )
        if abandoned:
            logger.info(f"Reclaimed {len(abandoned)} abandoned messages from Redis Streams.")
            for msg_id, envelope in abandoned:
                async with AsyncSessionLocal() as session:
                    await process_order_event(session, envelope)
                    await session.commit()
                await ack_message(redis_client, settings.ORDERS_STREAM, settings.INVENTORY_CONSUMER_GROUP, msg_id)
    except Exception as claim_err:
        logger.warning(f"Could not reclaim abandoned messages on startup: {claim_err}")

    while not stop_event.is_set():
        try:
            # Read batch of new messages
            messages = await read_from_group(
                redis=redis_client,
                stream=settings.ORDERS_STREAM,
                group=settings.INVENTORY_CONSUMER_GROUP,
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
                        await process_order_event(session, envelope)
                        await session.commit()

                    # Acknowledge receipt only after successful DB commit
                    await ack_message(redis_client, settings.ORDERS_STREAM, settings.INVENTORY_CONSUMER_GROUP, msg_id)

                except Exception as proc_err:
                    logger.error(f"Error processing order event {msg_id} ({envelope.event_id}): {proc_err}", exc_info=True)
                    # Send poison pills to DLQ
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
                    # Acknowledge to unblock stream
                    await ack_message(redis_client, settings.ORDERS_STREAM, settings.INVENTORY_CONSUMER_GROUP, msg_id)

        except asyncio.CancelledError:
            logger.info("Inventory Saga Consumer received cancellation.")
            break
        except Exception as loop_err:
            logger.error(f"Unexpected error in consumer loop: {loop_err}", exc_info=True)
            await asyncio.sleep(1.0)

    logger.info("Inventory Saga Consumer stopped.")
