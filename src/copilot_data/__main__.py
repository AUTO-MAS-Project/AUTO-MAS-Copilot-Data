"""手动与定时工作流共用的命令入口。"""

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from .publish import PublishError, publish
from .source import SNAPSHOT_VERSION, fetch_assignments, read_snapshot, write_snapshot

BRANCH = "refs/heads/data"
FILES = {
    "copilot": (Path("maa-copilot.json.gz"), Path("manifest.json")),
    "cultivate": (Path("cultivate_dataset.json.gz"), Path("cultivate_manifest.json")),
}
PARENT = Path(".data-parent")


def git(*args: str, env=None) -> str:
    return subprocess.check_output(["git", *args], text=True, env=env).strip()


def manifest_for(dataset: str, snapshot: dict, content: bytes) -> dict:
    return {
        "version": SNAPSHOT_VERSION if dataset == "copilot" else 2,
        "updatedAt": snapshot["updatedAt"]
        if dataset == "copilot"
        else snapshot["saved_at"],
        "count": snapshot["count"]
        if dataset == "copilot"
        else len(snapshot["operators"]),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def validate(dataset: str = "copilot") -> dict:
    path, manifest_path = FILES[dataset]
    content = path.read_bytes()
    if dataset == "cultivate":
        from .cultivate import read_snapshot as read_cultivate

        snapshot = read_cultivate(content)
    else:
        snapshot = read_snapshot(content)
    expected = manifest_for(dataset, snapshot, content)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not expected["count"] or manifest != expected:
        raise ValueError("快照或清单校验失败")
    return snapshot


def load(*, required: bool, dataset: str = "copilot") -> None:
    PARENT.unlink(missing_ok=True)
    paths = FILES[dataset]
    # 不允许 sync 误用当前目录中上次生成、但尚未保存到 data 分支的结果。
    for path in paths:
        path.unlink(missing_ok=True)
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", BRANCH],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 2:
        if required:
            raise ValueError("尚无 data 分支，请先运行 update")
        return
    result.check_returncode()
    git("fetch", "--depth=1", "origin", BRANCH)
    parent = git("rev-parse", "FETCH_HEAD")
    for path in paths:
        present = subprocess.run(
            ["git", "cat-file", "-e", f"{parent}:{path.name}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if present.returncode:
            if required:
                raise ValueError(f"data 分支尚无 {path.name}，请先运行 update")
            continue
        path.write_bytes(
            subprocess.check_output(["git", "show", f"{parent}:{path.name}"])
        )
    # 完整更新只需保留父提交；旧协议快照须重新生成，不能用于 sync 发布。
    if required:
        validate(dataset)
    PARENT.write_text(parent, encoding="ascii")


async def build(dataset: str = "copilot") -> None:
    path, manifest_path = FILES[dataset]
    if dataset == "cultivate":
        from .cultivate import build_snapshot

        snapshot = await build_snapshot()
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(
            gzip.compress(
                json.dumps(
                    snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode(),
                mtime=0,
            )
        )
        temporary.replace(path)
    else:
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
            entries = await fetch_assignments(
                client,
                progress=lambda loaded, total: print(
                    f"同步公开作业 {loaded}/{total}", flush=True
                ),
            )
        if not entries:
            raise ValueError("全站作业为空，拒绝覆盖旧快照")
        # 完整同步成功才续期，不把旧数据伪装成新同步。
        snapshot = write_snapshot(path, entries)
    manifest = manifest_for(dataset, snapshot, path.read_bytes())
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate(dataset)
    print(f"已生成 {path.name}，共 {manifest['count']} 条")


def save(dataset: str = "copilot") -> None:
    validate(dataset)
    path, manifest_path = FILES[dataset]
    parent = PARENT.read_text(encoding="ascii").strip() if PARENT.exists() else None
    with tempfile.TemporaryDirectory(prefix="copilot-index-") as directory:
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(directory) / "index"),
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        }
        # 两类快照共用 data 分支，只更新本轮产物，保留另一类的完整结果。
        git("read-tree", parent or "--empty", env=env)
        git("add", "--force", "--", path.name, manifest_path.name, env=env)
        tree = git("write-tree", env=env)
        if parent and tree == git("rev-parse", f"{parent}^{{tree}}"):
            return
        parents = ["-p", parent] if parent else []
        commit = git(
            "commit-tree",
            tree,
            *parents,
            "-m",
            f"chore(data): 更新 {dataset} 快照",
            env=env,
        )
    # 独立历史只含快照和清单；并发改动导致普通 push 拒绝，绝不强推。
    git("push", "origin", f"{commit}:{BRANCH}")
    PARENT.write_text(commit, encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("load", "build", "save", "publish"))
    parser.add_argument("--require-existing", action="store_true")
    parser.add_argument("--dataset", choices=FILES, default="copilot")
    args = parser.parse_args()
    try:
        if args.operation == "load":
            load(required=args.require_existing, dataset=args.dataset)
        elif args.operation == "build":
            asyncio.run(build(args.dataset))
        elif args.operation == "save":
            save(args.dataset)
        else:
            validate(args.dataset)
            asyncio.run(publish(FILES[args.dataset][0]))
    except (OSError, ValueError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        detail = str(exc) if isinstance(exc, PublishError) else type(exc).__name__
        print(f"{args.operation} 失败：{detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
