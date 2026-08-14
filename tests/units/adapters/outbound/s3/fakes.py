from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from typing import Any


class S3ProviderError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class CloseTrackingBody(BytesIO):
    def __init__(self, initial_bytes: bytes) -> None:
        super().__init__(initial_bytes)
        self.adapter_closed = False

    def close(self) -> None:
        self.adapter_closed = True
        super().close()


class FailingBody:
    def __init__(self) -> None:
        self.closed = False

    def read(self, _size: int) -> bytes:
        raise S3ProviderError("AccessDenied")

    def close(self) -> None:
        self.closed = True


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: dict[str, Exception] = {}
        self.last_body: CloseTrackingBody | None = None

    def fail(self, operation: str, error: Exception) -> None:
        self.errors[operation] = error

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self._raise_if_needed("put_object")
        body = kwargs["Body"].read()
        record = {
            "Body": body,
            "ContentType": kwargs.get("ContentType"),
            "ContentLength": len(body),
            "ETag": '"etag-123"',
            "ChecksumSHA256": "provider-sha256",
            "LastModified": datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            "Metadata": kwargs.get("Metadata", {}),
        }
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = record
        self.calls.append(("put_object", dict(kwargs)))
        return {"ETag": record["ETag"]}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("get_object")
        self.calls.append(("get_object", dict(kwargs)))
        record = self._record_for(kwargs["Bucket"], kwargs["Key"])
        response = dict(record)
        self.last_body = CloseTrackingBody(record["Body"])
        response["Body"] = self.last_body
        return response

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("head_object")
        self.calls.append(("head_object", dict(kwargs)))
        record = self._record_for(kwargs["Bucket"], kwargs["Key"])
        return {key: value for key, value in record.items() if key != "Body"}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("delete_object")
        self.calls.append(("delete_object", dict(kwargs)))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {}

    def _record_for(self, bucket_name: str, object_key: str) -> dict[str, Any]:
        key = (bucket_name, object_key)
        if key not in self.objects:
            raise S3ProviderError("NoSuchKey")
        return self.objects[key]

    def _raise_if_needed(self, operation: str) -> None:
        error = self.errors.get(operation)
        if error is not None:
            raise error


class BodylessS3Client(FakeS3Client):
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", dict(kwargs)))
        return {}


class FailingReadS3Client(FakeS3Client):
    def __init__(self, body: FailingBody) -> None:
        super().__init__()
        self._body = body

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", dict(kwargs)))
        return {"Body": self._body}


async def chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)
