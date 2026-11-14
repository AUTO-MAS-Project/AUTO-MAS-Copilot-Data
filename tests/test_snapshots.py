"""完整养成契约、两类快照共存和上传格式的回归验证。"""

import copy
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from copilot_data import __main__ as cli
from copilot_data import cultivate
from copilot_data import publish as publisher
from copilot_data.cultivate_source import (
    dataset_from_json,
    dataset_to_json,
    normalize_dataset,
    parse_operator_catalog,
)
from copilot_data.publish import upload
from copilot_data.source import write_snapshot


def source_data():
    return (
        {
            "char_test": {
                "name": "测试干员",
                "rarity": 5,
                "profession": "WARRIOR",
                "elite": [{}, {"4001": 1000, "3001": 2}, {"3002": 3}],
                "allSkill": [{"3001": 1}],
                "skills": [
                    {
                        "skillId": "skill_1",
                        "skillName": "无专精",
                        "skillLevelUpCost": None,
                    },
                    {
                        "skillId": "skill_2",
                        "skillName": "有专精",
                        "skillLevelUpCost": [[{"id": "3002", "count": 2}]],
                    },
                ],
                "equip": [
                    {
                        "uniEquipId": "mod_1",
                        "uniEquipName": "模组",
                        "typeName2": "X",
                        "itemCost": [{"3002": 2}],
                    }
                ],
            }
        },
        {
            "matrix": [
                {"stageId": "stage_1", "itemId": "3001", "times": 4, "quantity": 2},
                {"stageId": "stage_perm", "itemId": "3001", "times": 4, "quantity": 1},
            ]
        },
        {
            "data": [
                {"stageId": "stage_1", "stageCode": "1-7", "apCost": 6},
                {
                    "stageId": "stage_perm",
                    "stageCode": "TEST-1",
                    "apCost": 10,
                    "stageType": "ACT_PERM",
                },
            ]
        },
        [
            {
                "itemId": "3002",
                "resolve": False,
                "pathway": [{"itemId": "3001", "count": 3}],
            }
        ],
        [{"itemId": "3001", "itemValue": 5}],
    )


def snapshot():
    demand, *rest = source_data()
    return {
        "saved_at": 1700000000,
        "operators_saved_at": 1700000000,
        "dataset": dataset_to_json(
            normalize_dataset(demand, *rest, data_version="2023-11-14")
        ),
        "operators": parse_operator_catalog(demand),
    }


def write_cultivate():
    path, manifest_path = cli.FILES["cultivate"]
    payload = snapshot()
    content = gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), mtime=0)
    path.write_bytes(content)
    manifest_path.write_text(
        json.dumps(cli.manifest_for("cultivate", payload, content)), encoding="utf-8"
    )
    return content


def write_copilot(identifier=1):
    path, manifest_path = cli.FILES["copilot"]
    payload = write_snapshot(path, [{"id": identifier}], updated_at=1700000000)
    content = path.read_bytes()
    manifest_path.write_text(
        json.dumps(cli.manifest_for("copilot", payload, content)), encoding="utf-8"
    )
    return content


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CultivateTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_full_snapshot_from_same_demand_response(self):
        responses = dict(zip(cultivate.SOURCE_URLS, source_data()))
        requests = []

        def handle(request):
            requests.append(str(request.url))
            return httpx.Response(200, json=responses[str(request.url)])

        original = httpx.AsyncClient
        with patch.object(
            cultivate.httpx,
            "AsyncClient",
            side_effect=lambda **kw: original(
                transport=httpx.MockTransport(handle), **kw
            ),
        ):
            result = await cultivate.build_snapshot()
        self.assertCountEqual(requests, cultivate.SOURCE_URLS)
        self.assertEqual(result["saved_at"], result["operators_saved_at"])
        dataset = dataset_from_json(result["dataset"])
        self.assertEqual(
            [(drop.stage_id, drop.expected_per_run) for drop in dataset.drops],
            [("stage_1", 0.5)],
        )
        costs = {
            (entry.kind, entry.target_id, entry.level): dict(entry.items)
            for entry in dataset.demands["char_test"]
        }
        self.assertEqual(costs[("mastery", "skill_2", 1)], {"3002": 2})
        self.assertEqual(costs[("module", "mod_1", 1)], {"3002": 2})
        self.assertEqual(result["operators"][0]["skills"][0]["skillIndex"], 2)
        self.assertEqual(result["operators"][0]["maxElite"], 2)
        self.assertIn("wk_melee_6", dataset.stages)
        self.assertEqual(dataset.material_class["4001"], "farmable")
        self.assertEqual(
            cultivate.read_snapshot(
                gzip.compress(json.dumps(result).encode(), mtime=0)
            ),
            json.loads(json.dumps(result)),
        )

    async def test_build_writes_reproducible_gzip_and_hashes_compressed_bytes(self):
        payload = snapshot()
        with tempfile.TemporaryDirectory() as directory, working_directory(directory):
            with (
                patch.object(
                    cultivate, "build_snapshot", new=AsyncMock(return_value=payload)
                ),
                patch("builtins.print"),
            ):
                await cli.build("cultivate")
                path, manifest_path = cli.FILES["cultivate"]
                content = path.read_bytes()
                self.assertEqual(
                    json.loads(gzip.decompress(content)),
                    json.loads(json.dumps(payload)),
                )
                self.assertEqual(
                    cli.validate("cultivate"), json.loads(json.dumps(payload))
                )
                manifest = json.loads(manifest_path.read_bytes())
                self.assertEqual(
                    manifest["sha256"], hashlib.sha256(content).hexdigest()
                )
                self.assertFalse(Path("cultivate_dataset.json").exists())
                await cli.build("cultivate")
                self.assertEqual(path.read_bytes(), content)

    def test_plain_json_and_damaged_gzip_are_rejected(self):
        plain = json.dumps(snapshot()).encode()
        compressed = gzip.compress(plain, mtime=0)
        corrupted = bytearray(compressed)
        corrupted[-8] ^= 1
        for content in (plain, compressed[:12], bytes(corrupted)):
            with (
                self.subTest(content=content[:12]),
                self.assertRaisesRegex(ValueError, "压缩数据损坏"),
            ):
                cultivate.read_snapshot(content)

    async def test_empty_source_does_not_replace_last_complete_snapshot(self):
        responses = dict(zip(cultivate.SOURCE_URLS, source_data()))
        responses[cultivate.SOURCE_URLS[2]] = {"data": []}
        original = httpx.AsyncClient
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=responses[str(request.url)])
        )
        with tempfile.TemporaryDirectory() as directory, working_directory(directory):
            previous = write_cultivate()
            with patch.object(
                cultivate.httpx,
                "AsyncClient",
                side_effect=lambda **kw: original(transport=transport, **kw),
            ):
                with self.assertRaises(ValueError):
                    await cli.build("cultivate")
            self.assertEqual(Path("cultivate_dataset.json.gz").read_bytes(), previous)
            cli.validate("cultivate")

    async def test_invalid_source_rows_do_not_replace_last_complete_snapshot(self):
        for index, invalid in (
            (2, {"data": [{}]}),
            (2, [{}]),
            (2, {"stages": [{"stageId": "stage_1"}]}),
            (3, [{}]),
        ):
            with self.subTest(source=index, response=invalid):
                responses = dict(zip(cultivate.SOURCE_URLS, source_data()))
                responses[cultivate.SOURCE_URLS[index]] = invalid
                original = httpx.AsyncClient
                transport = httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json=responses[str(request.url)]
                    )
                )
                with (
                    tempfile.TemporaryDirectory() as directory,
                    working_directory(directory),
                ):
                    previous = write_cultivate()
                    manifest = Path("cultivate_manifest.json").read_bytes()
                    with patch.object(
                        cultivate.httpx,
                        "AsyncClient",
                        side_effect=lambda **kw: original(transport=transport, **kw),
                    ):
                        with self.assertRaises(ValueError):
                            await cli.build("cultivate")
                    self.assertEqual(
                        Path("cultivate_dataset.json.gz").read_bytes(), previous
                    )
                    self.assertEqual(
                        Path("cultivate_manifest.json").read_bytes(), manifest
                    )
                    cli.validate("cultivate")

    def test_partial_or_incompatible_cache_is_rejected(self):
        for change in (
            lambda value: value.pop("operators"),
            lambda value: value["dataset"].update(schema_version=1),
            lambda value: value["dataset"].update(drops=[]),
            lambda value: value.update(operators_saved_at=0),
            lambda value: value["operators"][0]["skills"][0].pop("skillIndex"),
            lambda value: value["operators"].append(
                copy.deepcopy(value["operators"][0])
            ),
        ):
            value = snapshot()
            change(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                cultivate.read_snapshot(
                    gzip.compress(json.dumps(value).encode(), mtime=0)
                )


class DataBranchTests(unittest.TestCase):
    def test_manifest_rejects_modified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, working_directory(directory):
            write_cultivate()
            value = snapshot()
            value["operators"][0]["label"] = "被修改的目录"
            Path("cultivate_dataset.json.gz").write_bytes(
                gzip.compress(json.dumps(value).encode(), mtime=0)
            )
            with self.assertRaisesRegex(ValueError, "清单校验失败"):
                cli.validate("cultivate")

    def test_alternating_saves_preserve_both_datasets_and_sync_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            checkout = root / "checkout"
            checkout.mkdir()
            subprocess.run(
                ["git", "init", "--bare", "--quiet", str(remote)], check=True
            )
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            with working_directory(checkout):
                cli.git("remote", "add", "origin", str(remote))
                cli.load(required=False)
                first_copilot = write_copilot()
                cli.save()
                cli.load(required=False, dataset="cultivate")
                complete_cultivate = write_cultivate()
                cli.save("cultivate")
                parent = cli.PARENT.read_text().strip()
                self.assertEqual(
                    subprocess.check_output(
                        ["git", "show", f"{parent}:maa-copilot.json.gz"]
                    ),
                    first_copilot,
                )
                cli.load(required=True, dataset="copilot")
                write_copilot(identifier=2)
                cli.save()
                parent = cli.PARENT.read_text().strip()
                self.assertEqual(
                    subprocess.check_output(
                        ["git", "show", f"{parent}:cultivate_dataset.json.gz"]
                    ),
                    complete_cultivate,
                )
                cli.load(required=True, dataset="cultivate")
                self.assertEqual(
                    Path("cultivate_dataset.json.gz").read_bytes(), complete_cultivate
                )
                self.assertEqual(cli.validate("cultivate")["saved_at"], 1700000000)

    def test_sync_requires_snapshot_saved_in_data_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            checkout = root / "checkout"
            checkout.mkdir()
            subprocess.run(
                ["git", "init", "--bare", "--quiet", str(remote)], check=True
            )
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            with working_directory(checkout):
                cli.git("remote", "add", "origin", str(remote))
                cli.load(required=False)
                write_copilot()
                cli.save()
                write_cultivate()
                with self.assertRaisesRegex(
                    ValueError, "尚无 cultivate_dataset.json.gz"
                ):
                    cli.load(required=True, dataset="cultivate")
                self.assertFalse(Path("cultivate_dataset.json.gz").exists())


class UploadTests(unittest.TestCase):
    def test_original_filename_and_mime_type_reach_upload(self):
        for filename, mime in (
            ("maa-copilot.json.gz", "application/gzip"),
            ("cultivate_dataset.json.gz", "application/gzip"),
        ):

            def execute(command, **kwargs):
                source_arg = command[command.index("--form") + 1]
                source = Path(source_arg.split(";type=")[0].removeprefix("file=@"))
                self.assertEqual(source.name, filename)
                self.assertEqual(source.read_bytes(), b"test snapshot")
                self.assertTrue(source_arg.endswith(f";type={mime}"))
                Path(command[command.index("--output") + 1]).write_text(
                    json.dumps({"code": 0, "data": {"id": 7}}), encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0, stdout="200", stderr="")

            with (
                self.subTest(filename=filename),
                patch("copilot_data.publish.subprocess.run", side_effect=execute),
            ):
                self.assertEqual(
                    upload(7, "test-key", b"test snapshot", filename=filename),
                    {"id": 7},
                )


class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_forwards_gzip_filename_and_checks_public_content(self):
        public_url = (
            "https://data.auto-mas.top/api/v1/files/auto-mas/Client/cultivate/download"
        )
        result = {
            "project_key": "auto-mas",
            "category_key": "Client",
            "file_key": "cultivate",
            "version": {"review_status": "approved", "version_no": 1},
            "published_version_no": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cultivate_dataset.json.gz"
            source.write_bytes(b"test snapshot")
            with (
                patch.object(
                    publisher, "target", return_value=(7, public_url, "test-key")
                ),
                patch.object(
                    publisher, "matches", new=AsyncMock(side_effect=[False, True])
                ) as matches,
                patch.object(publisher, "upload", return_value=result) as upload_mock,
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}),
                patch("builtins.print"),
            ):
                await publisher.publish(source)
                upload_mock.assert_called_once_with(
                    7,
                    "test-key",
                    b"test snapshot",
                    filename="cultivate_dataset.json.gz",
                )
                self.assertEqual(matches.await_count, 2)


if __name__ == "__main__":
    unittest.main()
