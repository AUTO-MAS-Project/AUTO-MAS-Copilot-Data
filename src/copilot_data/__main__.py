"""手动与定时工作流共用的命令入口。"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from .publish import PublishError, publish
from .source import fetch_assignments, read_snapshot, write_snapshot

BRANCH = "refs/heads/data"
SNAPSHOT = Path("maa-copilot.json.gz")
MANIFEST = Path("manifest.json")
PARENT = Path(".data-parent")


def git(*args: str, env=None) -> str:
    return subprocess.check_output(["git", *args], text=True, env=env).strip()


def validate() -> dict:
    content = SNAPSHOT.read_bytes()
    snapshot = read_snapshot(content)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not snapshot["count"] or manifest != {
        "version": 1,
        "updatedAt": snapshot["updatedAt"],
        "count": snapshot["count"],
        "sha256": hashlib.sha256(content).hexdigest(),
    }:
        raise ValueError("快照或清单校验失败")
    return snapshot


def load(*, required: bool) -> None:
    PARENT.unlink(missing_ok=True)
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
    for path in (SNAPSHOT, MANIFEST):
        path.write_bytes(
            subprocess.check_output(["git", "show", f"{parent}:{path.name}"])
        )
    validate()
    PARENT.write_text(parent, encoding="ascii")


async def build() -> None:
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        entries = await fetch_assignments(
            client,
            progress=lambda loaded, total: print(
                f"同步公开作业 {loaded}/{total}", flush=True
            ),
        )
    if not entries:
        raise ValueError("全站作业为空，拒绝覆盖旧快照")
    # 完整同步成功才续期。每天生成新时间戳，不把旧数据伪装成新同步。
    snapshot = write_snapshot(SNAPSHOT, entries)
    manifest = {
        "version": 1,
        "updatedAt": snapshot["updatedAt"],
        "count": snapshot["count"],
        "sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate()
    print(f"已生成 {snapshot['count']} 份作业快照")


def save() -> None:
    validate()
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
        git("read-tree", "--empty", env=env)
        git("add", "--force", "--", SNAPSHOT.name, MANIFEST.name, env=env)
        tree = git("write-tree", env=env)
        if parent and tree == git("rev-parse", f"{parent}^{{tree}}"):
            return
        parents = ["-p", parent] if parent else []
        commit = git(
            "commit-tree",
            tree,
            *parents,
            "-m",
            "chore(data): 更新全站作业快照",
            env=env,
        )
    # 独立历史只含快照和清单；并发改动导致普通 push 拒绝，绝不强推。
    git("push", "origin", f"{commit}:{BRANCH}")
    PARENT.write_text(commit, encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("load", "build", "save", "publish"))
    parser.add_argument("--require-existing", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "load":
            load(required=args.require_existing)
        elif args.operation == "build":
            asyncio.run(build())
        elif args.operation == "save":
            save()
        else:
            validate()
            asyncio.run(publish(SNAPSHOT))
    except (OSError, ValueError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        detail = str(exc) if isinstance(exc, PublishError) else type(exc).__name__
        print(f"{args.operation} 失败：{detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
