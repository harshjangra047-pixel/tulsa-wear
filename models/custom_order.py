from .database import db

class CustomOrder(db.Model):
    __tablename__ = "custom_orders"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    outfit_type = db.Column(db.String(150), nullable=False)
    fabric_preference = db.Column(db.String(100), nullable=True)
    color_preference = db.Column(db.String(100), nullable=True)
    embroidery_preference = db.Column(db.String(150), nullable=True)
    occasion = db.Column(db.String(150), nullable=True)
    measurements = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    reference_image = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default="Inquiry Received")
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<CustomOrder #{self.id} - {self.customer_name}>"
