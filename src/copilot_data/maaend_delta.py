"""自动选取正式基准，下载官方 ZIP、合并增量并逐基准验证；不运行 MaaEnd。"""

import argparse
import hashlib
import json
import os
import re
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


def release_version(tag: str) -> tuple[tuple[int, int, int], str, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(beta|rc)\.(\d+))?", tag)
    if not match:
        raise ValueError("无法识别官方版本标签")
    return tuple(map(int, match.group(1, 2, 3))), match[4] or "", int(match[5] or 0)


def release_catalog() -> list[dict]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AUTO-MAS-delta"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    releases = []
    for page in range(1, 21):
        with urlopen(
            Request(
                f"https://api.github.com/repos/MaaEnd/MaaEnd/releases?per_page=100&page={page}",
                headers=headers,
            ),
            timeout=30,
        ) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("官方发行记录不是列表")
        for item in batch:
            if item.get("draft"):
                continue
            try:
                release_version(item["tag_name"])
            except (ValueError, KeyError, TypeError):
                continue
            releases.append(item)
        if len(batch) < 100:
            return releases
    raise ValueError("官方发行记录分页超限")


def select_bases(releases: list[dict], target_tag: str, channel: str) -> list[str]:
    target, kind, _ = release_version(target_tag)
    stable = {
        release_version(item["tag_name"])[0]: item["tag_name"]
        for item in releases
        if not item.get("draft")
        and not item.get("prerelease")
        and not release_version(item["tag_name"])[1]
    }
    if channel == "stable":
        if kind:
            raise ValueError("正式通道不能发布 beta 目标")
        return [
            stable[value] for value in sorted(stable, reverse=True) if value < target
        ][:3]
    if not kind:
        raise ValueError("beta 通道必须指定 beta/rc 目标")
    return [stable[target]] if target in stable else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-tag", default="")
    parser.add_argument("--channel", choices=["stable", "beta"], required=True)
    parser.add_argument("--arch", choices=["x86_64", "aarch64"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    releases = release_catalog()
    if not args.target_tag:
        candidates = [
            item
            for item in releases
            if bool(release_version(item["tag_name"])[1]) == (args.channel == "beta")
        ]
        if not candidates:
            raise ValueError("通道没有可识别的发行版")
        args.target_tag = max(
            candidates, key=lambda item: release_version(item["tag_name"])
        )["tag_name"]
    bases = select_bases(releases, args.target_tag, args.channel)
    from .zip_delta import create_bundle
    from tempfile import TemporaryDirectory

    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output) as scratch:
        target = Path(scratch) / "target.zip"
        size, digest = download_release(args.target_tag, args.arch, target)
        archives = []
        for number, tag in enumerate(bases):
            archive = Path(scratch) / f"base-{number}.zip"
            download_release(tag, args.arch, archive)
            archives.append(archive)
        policy = {
            "channel": args.channel,
            "arch": args.arch,
            "target_version": args.target_tag,
            "target_size": size,
            "target_sha256": digest,
            "bases": bases,
            "beta_base": bases[0] if args.channel == "beta" and bases else None,
        }
        patch = args.output / "maaend.delta.zip"
        create_bundle(archives, target, patch, policy)
        print(
            f"{bases} -> {args.target_tag} ({args.arch}): {patch.stat().st_size} bytes; all plans verified"
        )


if __name__ == "__main__":
    main()
