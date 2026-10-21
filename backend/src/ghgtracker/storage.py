"""Where snapshot JPEGs live: a local directory (default) or an S3 compatible bucket (RustFS, ...).

Keys are always posix relative paths like `<login>/<session id>/<uuid>.jpg`; the database stores
exactly that, so switching the backend does not touch existing rows (only the files must be copied).
"""

import logging
import shutil
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ghgtracker.config import Settings, get_settings

log = logging.getLogger(__name__)


def check_key(key: str) -> str:
    """Reject keys that could escape their prefix (`..`, absolute paths, empty segments)."""
    if not key or any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key:
        raise ValueError(f"invalid key: {key!r}")
    return key


class SnapshotStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None:
        """The stored bytes, or None if the object does not exist."""

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def prepare(self) -> None:
        """Called once on startup: create the directory / bucket."""


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"invalid key: {key!r}")
        return path

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self._path(prefix), ignore_errors=True)


class S3Store:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                # Path style (http://host:9000/bucket/key) is what RustFS / MinIO expect.
                s3={"addressing_style": "path" if settings.s3_path_style else "auto"},
                retries={"max_attempts": 3, "mode": "standard"},
                # Newer boto3 versions add checksums that some S3 clones reject.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def prepare(self) -> None:
        """Create the bucket if needed. Retries, because RustFS may still be starting."""
        from botocore.exceptions import ClientError

        last_error: Exception | None = None
        for attempt in range(1, 31):
            try:
                try:
                    self.client.head_bucket(Bucket=self.bucket)
                except ClientError as exc:
                    if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
                        raise
                    self.client.create_bucket(Bucket=self.bucket)
                    log.info("created S3 bucket %s", self.bucket)
                return
            except Exception as exc:  # noqa: BLE001  (connection errors, 5xx while booting)
                last_error = exc
                log.warning("S3 not ready (attempt %d/30): %s", attempt, exc)
                time.sleep(2)
        raise RuntimeError(f"cannot reach S3 bucket {self.bucket!r}") from last_error

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=check_key(key), Body=data, ContentType="image/jpeg"
        )

    def get(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=check_key(key))

    def delete_prefix(self, prefix: str) -> None:
        check_key(prefix.rstrip("/"))
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/"):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})


@lru_cache
def get_store() -> SnapshotStore:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Store(settings)
    return LocalStore(settings.snapshot_dir)
