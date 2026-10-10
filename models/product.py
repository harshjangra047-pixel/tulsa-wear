from .database import db


class Product(db.Model):

    __tablename__ = "products"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    price = db.Column(
        db.Float,
        nullable=False
    )

    category = db.Column(
        db.String(100),
        nullable=False
    )

    fabric = db.Column(
        db.String(100)
    )

    color = db.Column(
        db.String(100)
    )

    description = db.Column(
        db.Text
    )

    image = db.Column(
        db.String(255)
    )

    stock = db.Column(
        db.Integer,
        default=0
    )

    best_seller = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )


    def __repr__(self):

        return (
            f"<Product {self.name}>"
        )
    gallery_images = db.relationship(
        "ProductImage",
        backref="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
        lazy="selectin",
    )
