"""Image storage abstraction for local filesystem and R2."""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

import aioboto3
from botocore.client import Config
from loguru import logger


class ImageStorage(ABC):
    """Abstract interface for image storage backends."""

    @abstractmethod
    async def store(self, content_hash: str, filename: str, data: bytes, content_type: str = "image/png") -> str:
        """Store image and return public URL."""

    @abstractmethod
    async def exists(self, content_hash: str) -> bool:
        """Check if any images exist for this content hash."""

    @abstractmethod
    async def delete_all(self, content_hash: str) -> None:
        """Delete all images for a content hash."""


class LocalImageStorage(ImageStorage):
    """Store images on local filesystem, served by gateway API."""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    async def store(self, content_hash: str, filename: str, data: bytes, content_type: str = "image/png") -> str:
        doc_dir = self.base_path / content_hash
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / filename).write_bytes(data)
        return f"/images/{content_hash}/{filename}"

    async def exists(self, content_hash: str) -> bool:
        return (self.base_path / content_hash).exists()

    async def delete_all(self, content_hash: str) -> None:
        images_dir = self.base_path / content_hash
        if images_dir.exists():
            shutil.rmtree(images_dir)


class R2ImageStorage(ImageStorage):
    """Store images in Cloudflare R2, served via custom domain CDN."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        public_url: str,
    ):
        self.bucket_name = bucket_name
        self.public_url = public_url.rstrip("/")
        self._session = aioboto3.Session()
        self._client_config = {
            "endpoint_url": f"https://{account_id}.r2.cloudflarestorage.com",
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": "auto",
            "config": Config(signature_version="s3v4"),
        }

    async def store(self, content_hash: str, filename: str, data: bytes, content_type: str = "image/png") -> str:
        key = f"{content_hash}/{filename}"
        async with self._session.client("s3", **self._client_config) as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        return f"{self.public_url}/{key}"

    async def exists(self, content_hash: str) -> bool:
        async with self._session.client("s3", **self._client_config) as s3:
            response = await s3.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"{content_hash}/",
                MaxKeys=1,
            )
            return response.get("KeyCount", 0) > 0

    async def delete_all(self, content_hash: str) -> None:
        async with self._session.client("s3", **self._client_config) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket_name, Prefix=f"{content_hash}/"):
                if "Contents" not in page:
                    continue

                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                if objects:
                    await s3.delete_objects(Bucket=self.bucket_name, Delete={"Objects": objects})
                    logger.debug(f"Deleted {len(objects)} images for {content_hash}")
