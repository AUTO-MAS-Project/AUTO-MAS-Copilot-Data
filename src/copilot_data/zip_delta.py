"""从旧 ZIP 复用压缩数据，重建远端 ZIP 的原始字节；调用方必须校验整包摘要。"""

import hashlib
import json
import struct
import threading
import zipfile
from pathlib import Path
from typing import BinaryIO

MAX_PATCH_BYTES = 32 * 1024**2


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_patch(baseline: Path, target: Path, patch: Path) -> None:
    """生成字节重建包，不包含上游私有增量清单或安装语义。"""
    operations = []
    with baseline.open("rb") as old, target.open("rb") as new:
        with zipfile.ZipFile(old) as old_zip, zipfile.ZipFile(new) as new_zip:
            previous = {item.filename: item for item in old_zip.infolist()}
            cursor = 0
            literals = []
            for item in sorted(new_zip.infolist(), key=lambda item: item.header_offset):
                candidate = previous.get(item.filename)
                start = _data_offset(new, item)
                if start < cursor:
                    raise ValueError("ZIP 区间冲突")
                if start > cursor:
                    literals.append((cursor, start - cursor))
                reusable = False
                if (
                    candidate is not None
                    and candidate.compress_size == item.compress_size
                ):
                    old_start = _data_offset(old, candidate)
                    old.seek(old_start)
                    new.seek(start)
                    remaining = item.compress_size
                    reusable = True
                    while remaining:
                        length = min(remaining, 1024 * 1024)
                        if old.read(length) != new.read(length):
                            reusable = False
                            break
                        remaining -= length
                if reusable and item.compress_size:
                    for offset, length in literals:
                        operations.append(["new", offset, length])
                    literals.clear()
                    operations.append(["old", old_start, item.compress_size])
                elif item.compress_size:
                    literals.append((start, item.compress_size))
                cursor = start + item.compress_size
            literals.append((cursor, target.stat().st_size - cursor))
            operations.extend(
                ["new", offset, length] for offset, length in literals if length
            )
        manifest = {
            "version": 1,
            "base_sha256": file_digest(baseline),
            "target_sha256": file_digest(target),
            "target_size": target.stat().st_size,
            "operations": [],
        }
        with zipfile.ZipFile(patch, "w", compression=zipfile.ZIP_DEFLATED) as output:
            with output.open("payload", "w", force_zip64=True) as payload:
                position = 0
                for kind, offset, length in operations:
                    if kind == "new":
                        new.seek(offset)
                        remaining = length
                        while remaining:
                            chunk = new.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise ValueError("ZIP 数据不完整")
                            payload.write(chunk)
                            remaining -= len(chunk)
                        offset = position
                        position += length
                    manifest["operations"].append([kind, offset, length])
            info = zipfile.ZipInfo("manifest.json")
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, json.dumps(manifest))
    if patch.stat().st_size >= min(MAX_PATCH_BYTES, target.stat().st_size):
        patch.unlink()
        raise ValueError("增量包未节省流量或超过发布限制，使用全量")


def apply_patch(
    baseline: Path,
    patch: Path,
    destination: Path,
    size: int,
    digest: str,
    cancelled: threading.Event,
) -> None:
    """重建归档，独立官方大小与 SHA256 校验通过才允许调用方安装。"""
    if patch.stat().st_size > MAX_PATCH_BYTES:
        raise ValueError("增量包过大")
    with zipfile.ZipFile(patch) as archive:
        info = archive.getinfo("manifest.json")
        if info.file_size > 16 * 1024**2:
            raise ValueError("增量清单过大")
        metadata = json.loads(archive.read(info))
        if (
            metadata.get("version") != 1
            or metadata.get("target_size") != size
            or metadata.get("target_sha256") != digest
            or metadata.get("base_sha256") != file_digest(baseline)
        ):
            raise ValueError("增量包与官方版本或本地基线不一致")
        operations = metadata["operations"]
        if len(operations) > 300_000 or archive.getinfo("payload").file_size > size:
            raise ValueError("增量包展开超限")
        with baseline.open("rb") as old, archive.open("payload") as payload:
            with destination.open("xb") as output:
                written = 0
                for kind, offset, length in operations:
                    if (
                        kind not in {"old", "new"}
                        or not isinstance(offset, int)
                        or not isinstance(length, int)
                        or offset < 0
                        or length < 0
                        or written + length > size
                    ):
                        raise ValueError("增量重建区间无效")
                    source = old if kind == "old" else payload
                    if kind == "new" and offset != payload.tell():
                        raise ValueError("增量数据顺序无效")
                    source.seek(offset)
                    remaining = length
                    while remaining:
                        if cancelled.is_set():
                            raise InterruptedError("增量重建已取消")
                        chunk = source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError("增量数据不完整")
                        output.write(chunk)
                        remaining -= len(chunk)
                    written += length
    if destination.stat().st_size != size or file_digest(destination) != digest:
        raise ValueError("重建包未通过官方 SHA256 校验")


def _data_offset(stream: BinaryIO, item: zipfile.ZipInfo) -> int:
    stream.seek(item.header_offset)
    header = stream.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise ValueError("ZIP 文件头无效")
    name_size, extra_size = struct.unpack_from("<HH", header, 26)
    return item.header_offset + 30 + name_size + extra_size
