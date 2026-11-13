"""下载官方两版 ZIP、生成字节增量并独立重建验证；不运行 MaaEnd。"""

import argparse
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def download_release(tag: str, arch: str, destination: Path) -> tuple[int, str]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?", tag):
        raise ValueError("只接受正式版或 beta 官方版本标签")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AUTO-MAS-delta"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/MaaEnd/MaaEnd/releases/tags/{quote(tag, safe='')}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        release = json.load(response)
    asset = next(
        item
        for item in release["assets"]
        if item["name"] == f"MaaEnd-win-{arch}-{tag}.zip"
    )
    size, digest = asset["size"], str(asset.get("digest", ""))
    if not 0 < size < 1024**3 or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("官方发行包缺少有效大小或 SHA256")
    if not asset["browser_download_url"].startswith(
        "https://github.com/MaaEnd/MaaEnd/releases/download/"
    ):
        raise ValueError("发行包下载地址无效")
    checksum, copied = hashlib.sha256(), 0
    with urlopen(asset["browser_download_url"], timeout=120) as response:
        with destination.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                copied += len(chunk)
                if copied > size:
                    raise ValueError("发行包下载超出官方大小")
                checksum.update(chunk)
                output.write(chunk)
    if copied != size or checksum.hexdigest() != digest[7:]:
        raise ValueError("发行包未通过官方 SHA256 校验")
    return size, digest[7:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-tag", required=True)
    parser.add_argument("--target-tag", required=True)
    parser.add_argument("--arch", choices=["x86_64", "aarch64"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.base_tag == args.target_tag:
        raise ValueError("起始和目标版本不能相同")
    from .zip_delta import apply_patch, create_patch

    args.output.mkdir(parents=True, exist_ok=True)
    baseline, target, rebuilt = (
        args.output / name for name in ("base.zip", "target.zip", "rebuilt.zip")
    )
    download_release(args.base_tag, args.arch, baseline)
    size, digest = download_release(args.target_tag, args.arch, target)
    patch = args.output / "maaend.delta.zip"
    create_patch(baseline, target, patch)
    apply_patch(baseline, patch, rebuilt, size, digest, threading.Event())
    print(
        f"{args.base_tag} -> {args.target_tag} ({args.arch}): "
        f"增量 {patch.stat().st_size} / 全量 {size} 字节，重建 SHA256 校验通过"
    )
    for path in (baseline, target, rebuilt):
        path.unlink()


if __name__ == "__main__":
    main()
