import logging
from io import BytesIO
from aiohttp import FormData

log = logging.getLogger("mt")


def header(config):
    return {"X-DDNet-Token": config.get("DDNET", "TOKEN")}



def upload_url(config):
    return config.get("DDNET", "UPLOAD")


def delete_url(config):
    return config.get("DDNET", "DELETE")


async def ddnet_upload(session, config, asset_type: str, buf: BytesIO, filename: str):
    url = upload_url(config)
    headers = header(config)

    if asset_type == "map":
        field_name = "map_name"
    elif asset_type == "log":
        field_name = "channel_name"
    elif asset_type in {"attachment", "avatar", "emoji"}:
        field_name = "asset_name"
    else:
        raise ValueError(f"Invalid asset type: {asset_type}")

    data = FormData()
    data.add_field("asset_type", asset_type)
    data.add_field(field_name, filename)
    data.add_field(
        "file",
        buf,
        filename=filename,
        content_type="application/octet-stream",
    )

    async with session.post(url, data=data, headers=headers) as resp:
        text = await resp.text()

        if resp.status != 200:
            log.error(
                "Upload failed (%s %s): %s (%d %s)",
                asset_type,
                filename,
                text,
                resp.status,
                resp.reason,
            )
            raise RuntimeError(text)

        log.info("Uploaded %s %s", asset_type, filename)


async def ddnet_delete(session, config, filename: str):
    url = delete_url(config)
    headers = header(config)

    data = {"map_name": filename}

    async with session.post(url, data=data, headers=headers) as resp:
        text = await resp.text()

        if resp.status != 200:
            log.error(
                "Delete failed %s: %s (%d %s)",
                filename,
                text,
                resp.status,
                resp.reason,
            )
            raise RuntimeError(text)

        log.info("Deleted %s", filename)

