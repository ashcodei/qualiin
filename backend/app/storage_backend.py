"""Storage abstraction for document files: local disk or S3."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Iterator

from .config import (
    STORAGE_BACKEND,
    STORAGE_DIR,
    S3_BUCKET,
    S3_PREFIX,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_REGION,
)


class StorageBackend(ABC):
    """Abstract storage: keys like 'original/{doc_id}.pdf', 'annotated/{doc_id}.pdf', 'results/{doc_id}.json'."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        pass

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        pass

    def get_path(self, key: str) -> Optional[Path]:
        """Return a local Path for the key if this backend is local (for FileResponse). Else None."""
        return None

    def get_stream(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Yield chunks for streaming (avoids loading full object into memory). Default uses get()."""
        data = self.get(key)
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]


class LocalStorage(StorageBackend):
    def __init__(self, base: Path):
        self.base = base
        (base / "original").mkdir(parents=True, exist_ok=True)
        (base / "annotated").mkdir(parents=True, exist_ok=True)
        (base / "results").mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.base / key.replace("\\", "/")

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    def get_path(self, key: str) -> Optional[Path]:
        p = self._path(key)
        return p if p.exists() else None


class S3Storage(StorageBackend):
    def __init__(self):
        import boto3
        from botocore.config import Config
        self.bucket = S3_BUCKET
        self.prefix = (S3_PREFIX.rstrip("/") + "/") if S3_PREFIX else ""
        kwargs = {"region_name": AWS_REGION} if AWS_REGION else {}
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
        self.client = boto3.client("s3", config=Config(signature_version="s3v4"), **kwargs)

    def _object_key(self, key: str) -> str:
        return self.prefix + key.replace("\\", "/")

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        return resp["Body"].read()

    def get_stream(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        resp = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        body = resp["Body"]
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._object_key(key), Body=data)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._object_key(key))
        except Exception:
            pass


def get_storage() -> StorageBackend:
    if STORAGE_BACKEND == "s3":
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        return S3Storage()
    return LocalStorage(STORAGE_DIR)


# Singleton used by jobs and main
_storage: Optional[StorageBackend] = None


def storage() -> StorageBackend:
    global _storage
    if _storage is None:
        _storage = get_storage()
    return _storage
