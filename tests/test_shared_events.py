"""
Unit tests for shared event envelope and domain payload models.
"""
from shared.events.base import EventEnvelope, EventType
from shared.events.order_payloads import OrderCreatedPayload, OrderItemPayload
from shared.events.stock_payloads import StockReservedPayload, StockReservationFailedPayload


def test_event_envelope_serialization():
    payload = {
        "order_id": "ord_123",
        "outlet_id": "out_01",
        "cashier_id": "usr_99",
        "items": [
            {"variant_id": "var_1", "sku": "TSHIRT-BLK-M", "quantity": 2, "unit_price": 25.0}
        ],
        "total_amount": 50.0,
    }

    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        aggregate_type="ORDER",
        aggregate_id="ord_123",
        correlation_id="corr_abc_123",
        causation_id="cause_xyz_789",
        producer="billing-service",
        payload=payload,
    )

    # Convert to Redis stream dictionary
    stream_dict = envelope.to_stream_dict()
    assert stream_dict["event_type"] == "ORDER_CREATED"
    assert stream_dict["aggregate_type"] == "ORDER"
    assert stream_dict["aggregate_id"] == "ord_123"
    assert stream_dict["correlation_id"] == "corr_abc_123"
    assert stream_dict["causation_id"] == "cause_xyz_789"
    assert stream_dict["producer"] == "billing-service"
    assert isinstance(stream_dict["payload"], str)

    # Reconstruct from stream dictionary
    reconstructed = EventEnvelope.from_stream_dict(stream_dict)
    assert reconstructed.event_id == envelope.event_id
    assert reconstructed.event_type == EventType.ORDER_CREATED
    assert reconstructed.payload["order_id"] == "ord_123"
    assert reconstructed.payload["total_amount"] == 50.0
    assert len(reconstructed.payload["items"]) == 1


def test_order_created_payload_validation():
    items = [
        OrderItemPayload(variant_id="v1", sku="SKU1", quantity=3, unit_price=10.5)
    ]
    order_payload = OrderCreatedPayload(
        order_id="ord_001",
        outlet_id="out_main",
        cashier_id="cashier_01",
        items=items,
        total_amount=31.5,
    )

    assert order_payload.order_id == "ord_001"
    assert order_payload.items[0].quantity == 3
    assert order_payload.total_amount == 31.5


def test_stock_payloads_validation():
    reserved = StockReservedPayload(
        order_id="ord_001",
        outlet_id="out_main",
        items=[OrderItemPayload(variant_id="v1", sku="SKU1", quantity=2, unit_price=15.0)],
    )
    assert reserved.order_id == "ord_001"
    assert reserved.items[0].quantity == 2

    failed = StockReservationFailedPayload(
        order_id="ord_001",
        outlet_id="out_main",
        failed_variant_id="v1",
        reason="Insufficient stock: 1 available, 2 requested",
    )
    assert failed.failed_variant_id == "v1"
    assert "Insufficient" in failed.reason
