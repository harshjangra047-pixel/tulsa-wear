from .database import db

class TrafficLog(db.Model):
    __tablename__ = "traffic_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), default="visit")  # visit, click, login, register, checkout, order_placed
    ip_address = db.Column(db.String(100), nullable=True)
    page_url = db.Column(db.String(255), nullable=True)
    referrer = db.Column(db.String(255), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    customer_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<TrafficLog #{self.id} {self.event_type} - {self.page_url}>"
