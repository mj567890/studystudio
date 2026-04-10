"""
apps/api/core/storage.py
MinIO 异步封装

C3（V2.6）：boto3 是同步 SDK，在 FastAPI async 路径中直接调用会阻塞事件循环。
          所有 MinIO 操作必须通过 AsyncMinIOClient，禁止直接调用 boto3 同步方法。
"""
import asyncio
import hashlib
import os
from functools import partial
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from apps.api.core.config import CONFIG


class AsyncMinIOClient:
    """
    所有 MinIO 操作的统一异步入口。
    使用 asyncio.get_event_loop().run_in_executor() 包装 boto3 同步调用，
    避免阻塞 FastAPI 事件循环。
    """

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=CONFIG.minio.endpoint,
            aws_access_key_id=CONFIG.minio.access_key,
            aws_secret_access_key=CONFIG.minio.secret_key,
        )
        self.bucket = CONFIG.minio.bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """确保 bucket 存在（同步，仅在初始化时调用一次）。"""
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    async def upload(self, key: str, src_path: str | Path) -> str:
        """上传文件到 MinIO，返回存储 URL。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._client.upload_file, str(src_path), self.bucket, key)
        )
        return f"{CONFIG.minio.endpoint}/{self.bucket}/{key}"

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """上传字节数据到 MinIO。"""
        import io
        loop = asyncio.get_event_loop()
        buf = io.BytesIO(data)
        await loop.run_in_executor(
            None,
            partial(
                self._client.upload_fileobj,
                buf, self.bucket, key,
                ExtraArgs={"ContentType": content_type}
            )
        )
        return f"{CONFIG.minio.endpoint}/{self.bucket}/{key}"

    async def download(self, key: str, dest_path: str | Path) -> Path:
        """从 MinIO 下载文件到本地路径，返回本地 Path。"""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._client.download_file, self.bucket, key, str(dest))
        )
        return dest

    async def download_bytes(self, key: str) -> bytes:
        """从 MinIO 下载文件内容为字节。"""
        import io
        buf = io.BytesIO()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._client.download_fileobj, self.bucket, key, buf)
        )
        return buf.getvalue()

    async def delete(self, key: str) -> None:
        """删除 MinIO 中的文件。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._client.delete_object, Bucket=self.bucket, Key=key)
        )

    async def presign(self, key: str, expires: int = 3600) -> str:
        """生成预签名 URL，默认有效期 1 小时。"""
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(
            None,
            partial(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires,
            )
        )
        return url

    async def exists(self, key: str) -> bool:
        """检查文件是否存在。"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                partial(self._client.head_object, Bucket=self.bucket, Key=key)
            )
            return True
        except ClientError:
            return False

    @staticmethod
    def compute_hash(file_path: str | Path) -> str:
        """计算文件 SHA-256，用于去重。"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


# 全局单例，应用启动时初始化
minio_client: AsyncMinIOClient | None = None


def get_minio_client() -> AsyncMinIOClient:
    global minio_client
    if minio_client is None:
        minio_client = AsyncMinIOClient()
    return minio_client
