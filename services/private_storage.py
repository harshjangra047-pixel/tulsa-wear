"""Private, durable storage for customer payment evidence."""

import io
import uuid

from PIL import Image


MAX_PROOF_BYTES = 3 * 1024 * 1024
ALLOWED_PROOF_TYPES = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


def upload_payment_proof(file_storage, order_id: int) -> str:
    stream = file_storage.stream
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size <= 0 or size > MAX_PROOF_BYTES:
        raise ValueError("Payment screenshot must be 3 MB or smaller.")

    content = stream.read(MAX_PROOF_BYTES + 1)
    if len(content) > MAX_PROOF_BYTES:
        raise ValueError("Payment screenshot must be 3 MB or smaller.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = image.format
    except Exception as exc:
        raise ValueError("Use a readable JPG, PNG, or WebP payment screenshot.") from exc
    if image_format not in ALLOWED_PROOF_TYPES:
        raise ValueError("Use a valid JPG, PNG, or WebP payment screenshot.")

    extension, content_type = ALLOWED_PROOF_TYPES[image_format]
    pathname = f"payment-proofs/{order_id}/{uuid.uuid4().hex}.{extension}"
    from services.media_storage import put_private_proof
    return put_private_proof(pathname, content, content_type)


def read_payment_proof(pathname: str):
    if not isinstance(pathname, str) or not pathname.startswith("payment-proofs/") or ".." in pathname:
        return None
    from services.media_storage import get_private_object
    return get_private_object(pathname)
