from datetime import datetime
from .database import db


class OrderNotification(db.Model):
    """
    Persistent audit log and outbox record for customer notifications.
    Supports transactional WhatsApp and Email dispatch, delivery webhooks,
    idempotency enforcement, and retry scheduling.
    """
    __tablename__ = "order_notifications"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, nullable=True, index=True)
    channel = db.Column(db.String(20), nullable=False)  # 'whatsapp' or 'email'
    event_type = db.Column(db.String(50), nullable=False)  # 'order_confirmation', 'payment_pending', 'order_dispatched', etc.
    recipient = db.Column(db.String(150), nullable=False)  # phone or email address
    status = db.Column(db.String(50), default="Pending", nullable=False)  # Pending, Queued, Sent, Delivered, Failed, Skipped, Not opted in
    provider_message_id = db.Column(db.String(150), nullable=True)
    attempt_count = db.Column(db.Integer, default=0, nullable=False)
    idempotency_key = db.Column(db.String(150), unique=True, nullable=False, index=True)
    last_error = db.Column(db.Text, nullable=True)
    payload_snapshot = db.Column(db.Text, nullable=True)  # JSON-serialized snapshot of message content
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "channel": self.channel,
            "event_type": self.event_type,
            "recipient": self.recipient,
            "status": self.status,
            "provider_message_id": self.provider_message_id,
            "attempt_count": self.attempt_count,
            "idempotency_key": self.idempotency_key,
            "last_error": self.last_error,
            "created_at": self.created_at.strftime("%d %b %Y, %I:%M %p") if self.created_at else None,
            "sent_at": self.sent_at.strftime("%d %b %Y, %I:%M %p") if self.sent_at else None,
            "delivered_at": self.delivered_at.strftime("%d %b %Y, %I:%M %p") if self.delivered_at else None
        }

    def __repr__(self):
        return f"<OrderNotification #{self.id} {self.channel}:{self.event_type} -> Order #{self.order_id} ({self.status})>"
