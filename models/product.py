from .database import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float, nullable=True)
    discount_percent = db.Column(db.Integer, nullable=True)

    # Primary Category & Multi-Category Assignments
    category = db.Column(db.String(100), nullable=False)
    category_2 = db.Column(db.String(100), nullable=True)
    category_3 = db.Column(db.String(100), nullable=True)
    category_4 = db.Column(db.String(100), nullable=True)

    fabric = db.Column(db.String(100))
    color = db.Column(db.String(100))
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    stock = db.Column(db.Integer, default=0)
    best_seller = db.Column(db.Boolean, default=False)

    # Shipping attributes
    weight_kg = db.Column(db.Float, default=0.5)
    length_cm = db.Column(db.Float, default=30.0)
    width_cm = db.Column(db.Float, default=25.0)
    height_cm = db.Column(db.Float, default=5.0)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    gallery_images = db.relationship(
        "ProductImage",
        backref="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
        lazy="selectin",
    )

    product_category_records = db.relationship(
        "ProductCategory",
        backref="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def alt_category_1(self):
        return self.category_2 or ""

    @property
    def alt_category_2(self):
        return self.category_3 or ""

    @property
    def alt_category_3(self):
        return self.category_4 or ""

    @property
    def all_categories(self):
        cats = []
        for c in [self.category, self.category_2, self.category_3, self.category_4]:
            if c and c.strip() and c.strip() not in cats:
                cats.append(c.strip())
        return cats

    @property
    def effective_discount_percent(self):
        if self.discount_percent is not None and self.discount_percent > 0:
            return int(round(self.discount_percent))
        if self.original_price and self.original_price > self.price and self.original_price > 0:
            return int(round(((self.original_price - self.price) / self.original_price) * 100))
        return 0

    @property
    def has_discount(self):
        return bool(
            (self.discount_percent and self.discount_percent > 0)
            or (self.original_price and self.original_price > self.price and self.original_price > 0)
        )

    @property
    def effective_original_price(self):
        if self.original_price and self.original_price > self.price:
            return self.original_price
        if self.discount_percent and self.discount_percent > 0:
            return round(self.price / (1.0 - (self.discount_percent / 100.0)), 2)
        return self.price

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

    def sync_categories(self, categories):
        from .product_category import ProductCategory
        clean = []
        for c in categories:
            if c and str(c).strip():
                item = str(c).strip()
                if item not in clean:
                    clean.append(item)
        if clean:
            self.category = clean[0]
            self.category_2 = clean[1] if len(clean) > 1 else None
            self.category_3 = clean[2] if len(clean) > 2 else None
            self.category_4 = clean[3] if len(clean) > 3 else None

        if self.id:
            existing = {pc.category: pc for pc in self.product_category_records}
            for cat_name, pc in list(existing.items()):
                if cat_name not in clean:
                    db.session.delete(pc)
            for idx, cat_name in enumerate(clean):
                if cat_name in existing:
                    existing[cat_name].is_primary = (idx == 0)
                else:
                    new_pc = ProductCategory(
                        product_id=self.id,
                        category=cat_name,
                        is_primary=(idx == 0),
                    )
                    db.session.add(new_pc)

    def __repr__(self):
        return f"<Product {self.name}>"
