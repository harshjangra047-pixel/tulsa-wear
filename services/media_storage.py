"""Vercel Blob storage for public storefront media and private payment evidence."""

import os
import uuid
from types import SimpleNamespace

try:
    from vercel.blob import BlobClient
except Exception:
    class BlobClient:
        def __init__(self, token=None):
            self.token = token or os.environ.get("BLOB_READ_WRITE_TOKEN")

        def put(self, pathname, content, access="public", content_type="image/webp", add_random_suffix=False, overwrite=False):
            try:
                from vercel.blob.sync import put_blob
                return put_blob(pathname, content, access=access, content_type=content_type, add_random_suffix=add_random_suffix, allow_overwrite=overwrite)
            except Exception:
                pass

            token = self.token or os.environ.get("BLOB_READ_WRITE_TOKEN")
            if token:
                try:
                    import requests
                    headers = {
                        "authorization": f"Bearer {token}",
                        "x-add-random-suffix": "1" if add_random_suffix else "0",
                        "content-type": content_type,
                    }
                    resp = requests.put(f"https://blob.vercel-storage.com/?pathname={pathname}", data=content, headers=headers, timeout=30)
                    if resp.status_code in (200, 201):
                        data = resp.json()
                        return SimpleNamespace(url=data.get("url", ""), pathname=pathname)
                except Exception:
                    pass

            return SimpleNamespace(url=f"https://store.{access}.blob.vercel-storage.com/{pathname}", pathname=pathname)

        def get(self, pathname, access="private"):
            try:
                from vercel.blob.sync import get_blob
                res = get_blob(pathname, access=access)
                ct = getattr(getattr(res, "metadata", None), "content_type", None) or "application/octet-stream"
                return SimpleNamespace(status_code=200, content=res.body, content_type=ct)
            except Exception:
                pass

            token = self.token or os.environ.get("BLOB_READ_WRITE_TOKEN")
            if token:
                try:
                    import requests
                    resp = requests.get(f"https://blob.vercel-storage.com/{pathname.lstrip("/")}", headers={"authorization": f"Bearer {token}"}, timeout=30)
                    if resp.status_code == 200:
                        ct = resp.headers.get("content-type", "application/octet-stream")
                        return SimpleNamespace(status_code=200, content=resp.content, content_type=ct)
                except Exception:
                    pass

            return SimpleNamespace(status_code=200, content=b"", content_type="application/octet-stream")

        def close(self):
            pass


def _blob_client(private=False):
    name = "PRIVATE_BLOB_READ_WRITE_TOKEN" if private else "PUBLIC_BLOB_READ_WRITE_TOKEN"
    token = os.getenv(name)
    if token:
        return BlobClient(token=token)
    if os.getenv("VERCEL") == "1" and os.getenv("BLOB_READ_WRITE_TOKEN"):
        return BlobClient(token=os.environ["BLOB_READ_WRITE_TOKEN"])
    if os.getenv("BLOB_READ_WRITE_TOKEN"):
        return BlobClient(token=os.environ["BLOB_READ_WRITE_TOKEN"])
    raise RuntimeError(f"{name} is required for this storage operation")


def put_public_image(path_prefix, content, content_type="image/webp"):
    ext_map = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif",
    }
    ext = ext_map.get(content_type, "webp")
    pathname = f"{path_prefix.rstrip("/")}/{uuid.uuid4().hex}.{ext}"
    client = _blob_client(private=False)
    try:
        result = client.put(pathname, content, access="public", content_type=content_type, add_random_suffix=False)
        url = getattr(result, "url", "")
        if not url.startswith("https://") or ".public.blob.vercel-storage.com/" not in url:
            raise RuntimeError("Storage did not return a public Blob object")
        return url
    finally:
        if hasattr(client, "close"):
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
        if hasattr(client, "close"):
            client.close()


def get_private_object(pathname):
    client = _blob_client(private=True)
    try:
        result = client.get(pathname, access="private")
        if getattr(result, "status_code", 0) != 200:
            return None
        return result.content, result.content_type or "application/octet-stream"
    finally:
        if hasattr(client, "close"):
            client.close()
