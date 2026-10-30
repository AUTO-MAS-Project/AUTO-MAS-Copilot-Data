"""生成完整一图流养成快照，解压后的 JSON 沿用 MAS 缓存结构。"""

import asyncio
import gzip
import json
import math
import time
import zlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .cultivate_source import (
    _DEMAND_URL,
    _ITEM_INFO_URL,
    _MATRIX_URL,
    _RECIPE_URL,
    _STAGE_INFO_URL,
    dataset_from_json,
    dataset_to_json,
    normalize_dataset,
    parse_operator_catalog,
    parse_recipes,
)

SOURCE_URLS = (_DEMAND_URL, _MATRIX_URL, _STAGE_INFO_URL, _RECIPE_URL, _ITEM_INFO_URL)


def read_snapshot(content: bytes) -> dict[str, Any]:
    """读取并验证 gzip 快照，不接受明文 JSON 或损坏的压缩数据。"""
    try:
        decoded = gzip.decompress(content)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError("养成快照压缩数据损坏，请重新生成") from exc
    return _validate_snapshot(json.loads(decoded))


def _validate_snapshot(payload: Any) -> dict[str, Any]:
    """验证材料数据与干员目录同时完整，不接受客户端的局部缓存。"""
    if not isinstance(payload, dict):
        raise ValueError("养成快照根节点必须是对象")
    for key in ("saved_at", "operators_saved_at"):
        stamp = payload.get(key)
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("养成快照缺少有效的生成时间")
    raw = payload.get("dataset")
    operators = payload.get("operators")
    if not isinstance(raw, dict) or raw.get("schema_version") != 2:
        raise ValueError("养成快照格式不兼容")
    for key, kind in (
        ("demands", dict),
        ("drops", list),
        ("stages", list),
        ("recipes", list),
        ("material_class", dict),
        ("item_value", dict),
        ("fixed_source_stages", dict),
    ):
        if not isinstance(raw.get(key), kind) or not raw[key]:
            raise ValueError(f"养成快照缺少完整的 {key}")
    if not isinstance(raw.get("data_version"), str) or not raw["data_version"]:
        raise ValueError("养成快照缺少数据版本")
    # 使用 MAS 的反序列化入口确认契约，不另造字段转换规则。
    try:
        dataset_from_json(raw)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("养成数据无法被 MAS 读取") from exc
    if not isinstance(operators, list) or not operators:
        raise ValueError("养成快照缺少干员目录")
    ids = set()
    for operator in operators:
        if (
            not isinstance(operator, dict)
            or not {
                "value",
                "label",
                "rarity",
                "profession",
                "maxElite",
                "maxSkillLevel",
                "dataMissing",
                "skills",
                "modules",
            }
            <= operator.keys()
        ):
            raise ValueError("干员目录缺少 MAS 所需字段")
        identifier = operator["value"]
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("干员目录编号无效或重复")
        ids.add(identifier)
        for field, required in (
            ("skills", {"value", "label", "maxLevel", "skillIndex"}),
            ("modules", {"value", "label", "maxLevel"}),
        ):
            options = operator[field]
            if not isinstance(options, list) or any(
                not isinstance(option, dict) or not required <= option.keys()
                for option in options
            ):
                raise ValueError("干员技能或模组目录不完整")
    if not raw["demands"].keys() <= ids:
        raise ValueError("养成需求与干员目录不一致")
    return payload


async def build_snapshot() -> dict[str, Any]:
    """五份公开源全部成功后，同批生成材料数据与干员目录。"""

    async def fetch(client: httpx.AsyncClient, url: str) -> Any:
        for attempt in range(3):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        demand, matrix, stages, recipes, items = await asyncio.gather(
            *(fetch(client, url) for url in SOURCE_URLS)
        )
    stage_entries = (
        stages
        if isinstance(stages, list)
        else (stages.get("data") or stages.get("stages"))
        if isinstance(stages, dict)
        else None
    )
    matrix_entries = matrix.get("matrix") if isinstance(matrix, dict) else matrix
    if (
        not isinstance(demand, dict)
        or not demand
        or not isinstance(matrix_entries, list)
        or not matrix_entries
        or not isinstance(stage_entries, list)
        or not stage_entries
        or not isinstance(recipes, list)
        or not recipes
        or not isinstance(items, list)
        or not items
    ):
        raise ValueError("一图流源数据为空或格式变化，拒绝发布")
    # 本地资源关和补充配方会让最终结果非空，须先检查源本身可用。
    if not any(
        isinstance(entry, dict)
        and isinstance(entry.get("stageId"), str)
        and entry["stageId"]
        and isinstance(entry.get("stageCode"), str)
        and entry["stageCode"]
        and type(entry.get("apCost")) in (int, float)
        and math.isfinite(entry["apCost"])
        and entry["apCost"] > 0
        for entry in stage_entries
    ):
        raise ValueError("一图流关卡源没有有效关卡，拒绝发布")
    if not parse_recipes(recipes):
        raise ValueError("一图流配方源没有有效配方，拒绝发布")
    stamp = int(time.time())
    dataset = normalize_dataset(
        demand,
        matrix,
        stages,
        recipes,
        items,
        data_version=datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d"),
    )
    payload = {
        "saved_at": stamp,
        "dataset": dataset_to_json(dataset),
        "operators": parse_operator_catalog(demand),
        "operators_saved_at": stamp,
    }
    return _validate_snapshot(payload)
