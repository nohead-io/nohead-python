from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from typing_extensions import Unpack

from ..._errors import UploadError
from ..._pagination import AsyncPaginator
from ..._uploads import Uploadable, open_upload
from ...models import Asset, AssetUsage, AssetWithUpload, DownloadUrl, ImageUrl
from ...params import AssetUploadCreate
from ._resource import AsyncResource


class AsyncAssets(AsyncResource):
    """Files of the key's project. `asset` is an asset ID (`ast_...`)."""

    async def upload(
        self,
        file: Uploadable,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        byte_size: int | None = None,
        idempotency_key: str | None = None,
    ) -> Asset:
        """Uploads a file and returns the `ready` asset: creates the upload, sends the
        bytes straight to storage, then completes it (which checks the file).

        `file` is bytes, a path, or a file opened in binary mode. Raises UploadError if
        storage refuses the bytes, and ValidationError if the file fails the checks.

        With an `idempotency_key`, running the same upload again resumes it: the key
        starts the upload, and an asset that is already `ready` is returned without
        sending the bytes again. Once the upload's URL has expired
        (`upload.expires_at`), it raises UploadError: start over with a new key.
        """
        source = open_upload(file, filename, content_type, byte_size)
        try:
            created = await self.create_upload(
                filename=source.filename,
                content_type=source.content_type,
                byte_size=source.byte_size,
                idempotency_key=idempotency_key,
            )
            # A replayed start returns the first run's asset, which may be done.
            if idempotency_key is not None:
                current = await self.get(created.id)
                if current.status == "ready":
                    return current
                # The key replays the first run's upload URL, which expires sooner.
                if created.upload.expires_at <= datetime.now(UTC):
                    raise UploadError(
                        f"The upload of {source.filename} expired: "
                        "start it again with a new idempotency_key"
                    )
            response = await self._client.put_upload(
                created.upload.url, created.upload.method, created.upload.headers, source
            )
        finally:
            source.close()
        if not response.is_success:
            raise UploadError(
                f"Storage refused the upload of {source.filename} ({response.status_code})",
                response.status_code,
            )
        return await self.complete(created.id)

    async def create_upload(
        self, *, idempotency_key: str | None = None, **params: Unpack[AssetUploadCreate]
    ) -> AssetWithUpload:
        """The first step of an upload: a `pending` asset with its `upload`, a presigned
        URL to PUT the bytes to (for example from a browser). Then `complete` it."""
        return await self._client.request(
            "assets_upload", cast=AssetWithUpload, body=params, idempotency_key=idempotency_key
        )

    async def complete(self, asset: str, *, idempotency_key: str | None = None) -> Asset:
        """Checks an uploaded file and marks the asset `ready`."""
        return await self._client.request(
            "assets_complete",
            cast=Asset,
            path={"asset_id": asset},
            idempotency_key=idempotency_key,
        )

    def list(
        self,
        *,
        content_type: str | Sequence[str] | None = None,
        deleted: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[Asset]:
        """`content_type` lists only assets of a type: a MIME type or a `type/*` wildcard
        (`"image/*"`), or a list of several (up to 50: `["image/*", "application/pdf"]`),
        for example the ones an asset field accepts (its `accepted_types`)."""
        types: str | dict[str, list[str]] | None = (
            content_type
            if content_type is None or isinstance(content_type, str)
            else {"in": list(content_type)}
        )
        return self._client.paginate(
            "assets_list",
            item=Asset,
            query={
                "filter": {"content_type": types, "deleted": deleted},
                "limit": limit,
                "cursor": cursor,
            },
        )

    async def get(self, asset: str) -> Asset:
        return await self._client.request("assets_get", cast=Asset, path={"asset_id": asset})

    async def delete(self, asset: str, *, idempotency_key: str | None = None) -> Asset:
        """Soft-deletes the asset; the file is purged at its `purge_after` (or sooner with
        `purge`), and `restore` brings it back until then."""
        return await self._client.request(
            "assets_delete",
            cast=Asset,
            path={"asset_id": asset},
            idempotency_key=idempotency_key,
        )

    async def restore(self, asset: str, *, idempotency_key: str | None = None) -> Asset:
        return await self._client.request(
            "assets_restore",
            cast=Asset,
            path={"asset_id": asset},
            idempotency_key=idempotency_key,
        )

    async def purge(self, asset: str, *, idempotency_key: str | None = None) -> Asset:
        """Permanently deletes a deleted asset now, instead of at its `purge_after`,
        and returns it as it was. It can't be restored; records that reference it keep
        the ID. Raises ConflictError if the asset isn't deleted: delete it first."""
        return await self._client.request(
            "assets_purge",
            cast=Asset,
            path={"asset_id": asset},
            idempotency_key=idempotency_key,
        )

    async def usage(self, asset: str) -> AssetUsage:
        """Where the asset is used: how many undeleted records use it (`records`), how
        many of them are published (`published`), and the 10 most recently updated with
        the fields they use it in (`uses`). Needs the `records:read` scope too."""
        return await self._client.request("assets_usage", cast=AssetUsage, path={"asset_id": asset})

    async def image_url(
        self,
        asset: str,
        *,
        width: int | None = None,
        height: int | None = None,
        fit: Literal["contain", "cover", "fill"] | None = None,
        format: Literal["original", "webp", "avif", "jpeg", "png"] | None = None,
        quality: int | None = None,
    ) -> ImageUrl:
        """A signed, cacheable URL of an image rendition (`url`)."""
        return await self._client.request(
            "assets_image_url",
            cast=ImageUrl,
            path={"asset_id": asset},
            query={
                "width": width,
                "height": height,
                "fit": fit,
                "format": format,
                "quality": quality,
            },
        )

    async def download_url(self, asset: str) -> DownloadUrl:
        """A 15-minute link to download the original file (`url`)."""
        return await self._client.request(
            "assets_download_url", cast=DownloadUrl, path={"asset_id": asset}
        )
