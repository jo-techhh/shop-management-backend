"""
Transactional Outbox background publisher worker for Billing Service.
Pulls uncommitted outbox events, pushes to Redis Streams (stream:orders), and marks them PUBLISHED.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.billing_service.src.config import settings
from services.billing_service.src.db.session import AsyncSessionLocal
from services.billing_service.src.models.outbox import OutboxEvent
from shared.broker.streams import publish_to_stream, send_to_dlq
from shared.events.base import EventEnvelope, EventType

logger = logging.getLogger("billing_outbox_worker")


async def run_outbox_worker(redis_client: aioredis.Redis, stop_event: asyncio.Event) -> None:
    """Continuous polling loop that publishes pending outbox events to stream:orders."""
    logger.info("Billing Outbox Publisher Worker started.")
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(OutboxEvent)
                    .where(OutboxEvent.status == "PENDING")
                    .order_by(OutboxEvent.created_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL)
                    continue

                for outbox in events:
                    try:
                        envelope = EventEnvelope(
                            event_id=outbox.event_id,
                            event_type=EventType(outbox.event_type),
                            aggregate_type=outbox.aggregate_type,
                            aggregate_id=outbox.aggregate_id,
                            correlation_id=outbox.correlation_id,
                            causation_id=outbox.causation_id,
                            producer="billing-service",
                            payload=json.loads(outbox.payload_json),
                        )

                        # Publish to stream:orders
                        await publish_to_stream(
                            redis=redis_client,
                            stream=settings.ORDERS_STREAM,
                            event=envelope,
                        )

                        outbox.status = "PUBLISHED"
                        outbox.published_at = datetime.now(timezone.utc)
                        logger.info(f"Published order event {outbox.event_type} ({outbox.event_id}) to {settings.ORDERS_STREAM}")

                    except Exception as pub_err:
                        outbox.retry_count += 1
                        logger.error(f"Error publishing outbox event {outbox.event_id}: {pub_err}")
                        if outbox.retry_count >= 5:
                            outbox.status = "FAILED"
                            await send_to_dlq(
                                redis=redis_client,
                                dlq_stream=settings.DLQ_STREAM,
                                raw_message_id=outbox.event_id,
                                event_data={
                                    "event_id": outbox.event_id,
                                    "event_type": outbox.event_type,
                                    "correlation_id": outbox.correlation_id,
                                    "payload": outbox.payload,
                                },
                                error_message=str(pub_err),
                                retry_count=outbox.retry_count,
                                consumer_name="billing-outbox-worker",
                            )

                await session.commit()

        except asyncio.CancelledError:
            logger.info("Billing Outbox Publisher Worker received cancellation.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in outbox worker loop: {e}", exc_info=True)
            await asyncio.sleep(1.0)

    logger.info("Billing Outbox Publisher Worker stopped.")
