"""
Redis Streams event broker utilities: publishing, consumer group management,
acknowledgments, claiming pending unacked messages, and Dead Letter Queue (DLQ) routing.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from shared.events.base import EventEnvelope

logger = logging.getLogger("redis_streams")


async def ensure_consumer_group(
    redis: aioredis.Redis,
    stream: str,
    group: str,
    start_id: str = "$",
) -> None:
    """
    Idempotently creates a consumer group on a Redis Stream.
    If the stream or group already exists, BUSYGROUP errors are caught cleanly.
    """
    try:
        await redis.xgroup_create(name=stream, groupname=group, id=start_id, mkstream=True)
        logger.info(f"Consumer group '{group}' created on stream '{stream}' (start_id={start_id}).")
    except ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.debug(f"Consumer group '{group}' already exists on stream '{stream}'.")
        else:
            raise


async def publish_to_stream(
    redis: aioredis.Redis,
    stream: str,
    event: EventEnvelope,
    max_len: int = 100000,
) -> str:
    """
    Publishes an event to a Redis Stream via XADD with length capping.
    Returns the generated Redis Stream entry ID (e.g., '1727371234567-0').
    """
    payload_dict = event.to_stream_dict()
    entry_id = await redis.xadd(
        name=stream,
        fields=payload_dict,
        maxlen=max_len,
        approximate=True,
    )
    logger.debug(f"Published event {event.event_type} ({event.event_id}) to {stream} as {entry_id}.")
    return entry_id


async def read_from_group(
    redis: aioredis.Redis,
    stream: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 2000,
) -> List[Tuple[str, EventEnvelope]]:
    """
    Reads new unread messages ('<') from a consumer group via XREADGROUP.
    Returns a list of (message_id, EventEnvelope).
    """
    try:
        results = await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
    except ResponseError as e:
        logger.error(f"Error reading from group {group} on {stream}: {e}")
        return []

    events: List[Tuple[str, EventEnvelope]] = []
    if not results:
        return events

    for stream_name, messages in results:
        for msg_id, raw_fields in messages:
            try:
                envelope = EventEnvelope.from_stream_dict(raw_fields)
                events.append((msg_id, envelope))
            except Exception as ex:
                logger.error(f"Failed to deserialize event {msg_id} from {stream_name}: {ex}")
    return events


async def ack_message(
    redis: aioredis.Redis,
    stream: str,
    group: str,
    message_id: str,
) -> int:
    """Acknowledge successful event processing via XACK."""
    return await redis.xack(stream, group, message_id)


async def send_to_dlq(
    redis: aioredis.Redis,
    dlq_stream: str,
    raw_message_id: str,
    event_data: Dict[str, Any],
    error_message: str,
    retry_count: int,
    consumer_name: str,
) -> str:
    """
    Routes unprocessable poison pill or failed messages to the Dead Letter Queue.
    Persists error details, stack trace summary, and original payload.
    """
    dlq_payload = {
        "original_message_id": raw_message_id,
        "event_id": event_data.get("event_id", "unknown"),
        "event_type": event_data.get("event_type", "unknown"),
        "correlation_id": event_data.get("correlation_id", "unknown"),
        "consumer": consumer_name,
        "retry_count": str(retry_count),
        "error": error_message,
        "payload": json.dumps(event_data.get("payload", {})),
    }
    dlq_id = await redis.xadd(name=dlq_stream, fields=dlq_payload)
    logger.warning(f"Sent failed event {raw_message_id} to DLQ {dlq_stream} as {dlq_id}: {error_message}")
    return dlq_id


async def claim_abandoned_messages(
    redis: aioredis.Redis,
    stream: str,
    group: str,
    consumer: str,
    min_idle_time_ms: int = 60000,
    count: int = 10,
) -> List[Tuple[str, EventEnvelope]]:
    """
    Uses XAUTOCLAIM to reclaim pending messages from workers that crashed before sending XACK.
    Guarantees at-least-once delivery recovery after worker failures.
    """
    try:
        # xautoclaim returns (next_start_id, [(msg_id, fields), ...], [deleted_ids])
        result = await redis.xautoclaim(
            name=stream,
            groupname=group,
            consumername=consumer,
            min_idle_time=min_idle_time_ms,
            start_id="0-0",
            count=count,
        )
        if not result or len(result) < 2:
            return []

        claimed_messages = result[1]
        events: List[Tuple[str, EventEnvelope]] = []
        for msg_id, raw_fields in claimed_messages:
            try:
                envelope = EventEnvelope.from_stream_dict(raw_fields)
                events.append((msg_id, envelope))
            except Exception as ex:
                logger.error(f"Failed to deserialize claimed event {msg_id}: {ex}")
        return events
    except ResponseError as e:
        logger.error(f"Error during XAUTOCLAIM on {stream}/{group}: {e}")
        return []
