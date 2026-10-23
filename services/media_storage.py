"""Vercel Blob storage for public storefront media and private payment evidence."""

import os
import uuid

try:
    from vercel.blob import BlobClient
except ImportError:
    class BlobClient:
        def __init__(self, token=None):
            self.token = token


def _blob_client(private=False):
    name = "PRIVATE_BLOB_READ_WRITE_TOKEN" if private else "PUBLIC_BLOB_READ_WRITE_TOKEN"
    token = os.getenv(name)
    if token:
        return BlobClient(token=token)
    if os.getenv("VERCEL") == "1" and os.getenv("BLOB_READ_WRITE_TOKEN"):
        return BlobClient(token=os.environ["BLOB_READ_WRITE_TOKEN"])
    raise RuntimeError(f"{name} is required for this storage operation")


def put_public_image(path_prefix, content, content_type="image/webp"):
    extension = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif",
    }.get(content_type, "webp")
    pathname = f"{path_prefix.rstrip('/')}/{uuid.uuid4().hex}.{extension}"
    client = _blob_client(private=False)
    try:
        result = client.put(pathname, content, access="public", content_type=content_type, add_random_suffix=False)
        url = getattr(result, "url", "")
        if not url.startswith("https://") or ".public.blob.vercel-storage.com/" not in url:
            raise RuntimeError("Storage did not return a public Blob object")
        return url
    finally:
        client.close()


def put_private_proof(pathname, content, content_type):
    client = _blob_client(private=True)
    try:
        result = client.put(pathname, content, access="private", content_type=content_type)
        url = getattr(result, "url", "")
        stored_path = getattr(result, "pathname", pathname)
        if not url.startswith("https://") or ".private.blob.vercel-storage.com/" not in url:
            raise RuntimeError("Storage did not return a private Blob object")
        if stored_path != pathname:
            raise RuntimeError("Storage returned an unexpected object path")
        return stored_path
    finally:
        client.close()


def get_private_object(pathname):
    client = _blob_client(private=True)
    try:
        result = client.get(pathname, access="private")
        if getattr(result, "status_code", 0) != 200:
            return None
        return result.content, result.content_type or "application/octet-stream"
    finally:
        client.close()
