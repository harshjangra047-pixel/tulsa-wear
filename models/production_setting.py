"""Production Settings and Atelier Capacity Configuration."""
from .database import db


class ProductionSetting(db.Model):
    __tablename__ = "production_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Atelier Capacity Configuration
    workers_count = db.Column(db.Integer, default=4, nullable=False)
    working_hours_per_day = db.Column(db.Float, default=8.0, nullable=False)
    working_days_per_week = db.Column(db.Integer, default=6, nullable=False)
    daily_capacity_hours = db.Column(db.Float, default=32.0, nullable=False)

    # Standard Estimated Preparation Minutes per Garment Category
    kurti_prep_minutes = db.Column(db.Integer, default=120, nullable=False)        # 2 hours
    palazzo_prep_minutes = db.Column(db.Integer, default=180, nullable=False)      # 3 hours
    embroidered_prep_minutes = db.Column(db.Integer, default=300, nullable=False)  # 5 hours
    partywear_prep_minutes = db.Column(db.Integer, default=480, nullable=False)    # 8 hours
    batch_setup_minutes = db.Column(db.Integer, default=30, nullable=False)        # 30 min batch setup

    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    @classmethod
    def get_settings(cls):
        """Retrieve current singleton settings or create default."""
        settings = cls.query.first()
        if not settings:
            settings = cls(
                workers_count=4,
                working_hours_per_day=8.0,
                working_days_per_week=6,
                daily_capacity_hours=32.0,
                kurti_prep_minutes=120,
                palazzo_prep_minutes=180,
                embroidered_prep_minutes=300,
                partywear_prep_minutes=480,
                batch_setup_minutes=30
            )
            try:
                db.session.add(settings)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return settings

    def to_dict(self):
        return {
            "workers_count": self.workers_count,
            "working_hours_per_day": self.working_hours_per_day,
            "working_days_per_week": self.working_days_per_week,
            "daily_capacity_hours": self.daily_capacity_hours,
            "kurti_prep_minutes": self.kurti_prep_minutes,
            "palazzo_prep_minutes": self.palazzo_prep_minutes,
            "embroidered_prep_minutes": self.embroidered_prep_minutes,
            "partywear_prep_minutes": self.partywear_prep_minutes,
            "batch_setup_minutes": self.batch_setup_minutes,
        }

