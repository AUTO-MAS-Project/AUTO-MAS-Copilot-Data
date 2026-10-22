"""使用下载站 Access Key 上传，回读公开地址确认已发布。"""

import asyncio
import hashlib
import os
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx

BASE = "https://data.auto-mas.top"
MAX_BYTES = 32 * 1024 * 1024


class PublishError(ValueError):
    pass


def target() -> tuple[int, str, str]:
    identifier = os.environ.get("AUTOMAS_FILE_ID", "")
    public_url = os.environ.get("AUTOMAS_PUBLIC_URL", "")
    token = os.environ.get("AUTOMAS_TOKEN", "")
    public = urlsplit(public_url)
    if not identifier.isdecimal() or int(identifier) < 1:
        raise PublishError("请配置 AUTOMAS_FILE_ID 仓库变量（目标文件的数字 ID）")
    if (
        public.scheme != "https"
        or public.netloc != urlsplit(BASE).netloc
        or public.query
        or public.fragment
        or not public.path.startswith("/api/v1/files/")
        or not public.path.endswith("/download")
    ):
        raise PublishError("请配置 AUTOMAS_PUBLIC_URL 为下载站的固定公开下载地址")
    if not token.strip() or "\r" in token or "\n" in token:
        raise PublishError("请配置 AUTOMAS_TOKEN Actions Secret")
    return int(identifier), public_url, token


async def matches(client: httpx.AsyncClient, url: str, expected: str) -> bool:
    try:
        digest, size = hashlib.sha256(), 0
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    return False
                digest.update(chunk)
        return digest.hexdigest() == expected
    except httpx.HTTPError:
        return False


async def upload(
    client: httpx.AsyncClient, file_id: int, token: str, content: bytes
) -> dict | None:
    url = f"{BASE}/api/v1/user/files/{file_id}/versions"
    # 同站 307/308 可重放表单；不向其他站点转发机器凭证，不重试不确定的 POST。
    for _ in range(6):
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("maa-copilot.json.gz", content, "application/gzip")},
            data={
                "change_note": f"GitHub Actions run {os.environ.get('GITHUB_RUN_ID', 'manual')}"
            },
        )
        if response.status_code in {307, 308}:
            location = urljoin(url, response.headers.get("location", ""))
            parsed = urlsplit(location)
            if (
                parsed.scheme != "https"
                or parsed.netloc != urlsplit(BASE).netloc
                or parsed.username
                or parsed.password
            ):
                raise PublishError("下载站上传发生跨站重定向，已停止")
            url = location
            continue
        if response.status_code == 409:
            return None  # 仅随后公开回读一致才将重复内容视为成功。
        if not 200 <= response.status_code < 300:
            raise PublishError(f"下载站上传失败（HTTP {response.status_code}）")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise PublishError("下载站未确认上传成功")
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("id") != file_id:
            raise PublishError("下载站返回的目标文件不一致")
        return data
    raise PublishError("下载站上传重定向次数过多")


async def publish(source: Path) -> None:
    file_id, public_url, token = target()
    content = source.read_bytes()
    if not content or len(content) > MAX_BYTES:
        raise PublishError("快照大小不合法")
    expected = hashlib.sha256(content).hexdigest()
    async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
        if await matches(client, public_url, expected):
            print("公开下载内容一致，无须重复上传")
            return
        data = await upload(client, file_id, token, content)
        if data is not None:
            keys = [
                data.get(key) for key in ("project_key", "category_key", "file_key")
            ]
            if any(not isinstance(key, str) or not key for key in keys):
                raise PublishError("上传结果缺少公开路径")
            actual_url = (
                BASE
                + "/api/v1/files/"
                + "/".join(quote(key, safe="") for key in keys)
                + "/download"
            )
            if actual_url != public_url:
                raise PublishError("公开下载地址与上传目标不一致")
            version = data.get("version")
            if (
                not isinstance(version, dict)
                or version.get("review_status") != "approved"
                or not isinstance(version.get("version_no"), int)
                or data.get("published_version_no") != version["version_no"]
            ):
                raise PublishError("快照已上传但尚未发布，请使用有发布权限的账号凭证")
        for attempt in range(6):
            if await matches(client, public_url, expected):
                print(f"下载站公开内容校验通过：{public_url}")
                if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
                    with open(summary, "a", encoding="utf-8") as stream:
                        stream.write(f"\n下载站发布成功：[公开快照]({public_url})\n")
                return
            if attempt < 5:
                await asyncio.sleep(5)
    raise PublishError("公开下载内容与快照不一致，请检查审核状态或 CDN 缓存")
