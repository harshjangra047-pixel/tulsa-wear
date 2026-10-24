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

    # Shipping attributes
    weight_kg = db.Column(
        db.Float,
        default=0.5
    )

    length_cm = db.Column(
        db.Float,
        default=30.0
    )

    width_cm = db.Column(
        db.Float,
        default=25.0
    )

    height_cm = db.Column(
        db.Float,
        default=5.0
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )


    @property
    def primary_photo_url(self):
        if self.gallery_images:
            for item in self.gallery_images:
                if item.image_url and item.image_url.strip():
                    return item.image_url.strip()
        return self.image or "product-1.jpg"

    @property
    def all_photo_urls(self):
        urls = []
        if self.gallery_images:
            for item in self.gallery_images:
                if item.image_url and item.image_url.strip():
                    clean = item.image_url.strip()
                    if clean not in urls:
                        urls.append(clean)
        if not urls and self.image:
            urls.append(self.image.strip())
        if not urls:
            urls.append("product-1.jpg")
        return urls

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
