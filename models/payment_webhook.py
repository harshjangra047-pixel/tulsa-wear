"""Payment Webhook Event model for Razorpay Webhook Idempotency & Audit."""
from datetime import datetime
from .database import db


class PaymentWebhookEvent(db.Model):
    __tablename__ = "payment_webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    razorpay_order_id = db.Column(db.String(100), nullable=True, index=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True, index=True)
    order_id = db.Column(db.Integer, nullable=True, index=True)
    amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default="INR")
    status = db.Column(db.String(50), default="Processed")  # Processed, Ignored, Failed
    error_message = db.Column(db.Text, nullable=True)
    payload = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    def __repr__(self):
        return f"<PaymentWebhookEvent {self.event_id} - {self.event_type} - {self.status}>"
