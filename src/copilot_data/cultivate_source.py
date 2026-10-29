#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team

#   This file is part of AUTO-MAS.

#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.

#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
#   the GNU Affero General Public License for more details.

#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.

#   Contact: DLmaster_361@163.com


"""MAS 养成快照的独立整理规则。

来源：AUTO-MAS-Project/AUTO-MAS@2ac826c8cebad7725e9854b4c70f6c43f24d2712
app/task/MAA/tools/cultivate/{types,yituliu}.py。
仅摘录纯数据类型、常量与解析函数；同步规则时保留与 MAS 的格式兼容。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


MAS_SOURCE_REVISION = "2ac826c8cebad7725e9854b4c70f6c43f24d2712"


GoalKind = Literal["elite", "skill", "mastery", "module"]


MaterialClass = Literal["farmable", "synthesizable", "unobtainable"]


@dataclass(frozen=True)
class DemandEntry:
    """单干员单档养成消耗（来自需求表，按实例分级存储）。"""

    kind: GoalKind
    target_id: str  # mastery=skillId；module=uniEquipId；elite=""
    level: int  # 该档把对应维度升到的等级；区间求和按 current < level <= to 取用
    items: Mapping[str, int]  # itemId -> 数量


@dataclass(frozen=True)
class DropEntry:
    """单关单材料掉落期望（占位 ID 已在数据层过滤）。"""

    stage_id: str
    item_id: str
    expected_per_run: float  # quantity/times，每次期望掉落
    start_ms: int  # 时间窗下界（epoch 毫秒，0 = 不限）
    end_ms: int | None  # 时间窗上界（epoch 毫秒，None = 不限）


@dataclass(frozen=True)
class StageMeta:
    """关卡元数据；资源本/芯片本由 13 关常量表补齐（yituliu 数据层）。"""

    stage_id: str
    stage_code: str
    ap_cost: int
    open_weekdays: tuple[int, ...] | None  # 0=周一..6=周日；None = 无星期限制
    composite: float = 0.0  # 综合效率：Σ(每次掉落期望×物品价值)/理智，展示时 ×100%


@dataclass(frozen=True)
class Recipe:
    """合成关系：1 个 result 由 ingredients 合成（composite 表的逆向边）。"""

    result_item_id: str
    ingredients: Mapping[str, int]


@dataclass(frozen=True)
class CultivateDataSet:
    """内核消费的数据集契约；一图流适配器与未来 MAA raise_demand 适配器都产出它。"""

    demands: Mapping[str, tuple[DemandEntry, ...]]  # char_id -> 档位列表
    drops: tuple[DropEntry, ...]
    stages: Mapping[str, StageMeta]  # stage_id -> 元数据
    recipes: tuple[Recipe, ...]
    material_class: Mapping[str, MaterialClass]  # 物品三分类（数据层预计算）
    fixed_source_stages: Mapping[str, str] = field(
        default_factory=dict
    )  # itemId -> stageId：资源关固定产出（无掉落统计，如采购凭证 ← AP-5）
    item_value: Mapping[str, float] = field(
        default_factory=dict
    )  # 物品价值（理智等价）
    data_version: str = ""  # 快照版本（抓取日期 + 源标识）


# 一图流现架构为"静态 COS + 前端本地计算"，旧 API（/stage/t3 等）已 404
_DEMAND_URL = (
    "https://cdn.jsdelivr.net/gh/Arknights-yituliu/frontend-v2-plus@main"
    "/src/static/json/operator/character_table_simple.v2.json"
)
_MATRIX_URL = "https://cos.yituliu.cn/arknights/stage-drop/matrix.json"
_STAGE_INFO_URL = "https://backend.yituliu.cn/stage/info"
_RECIPE_URL = (
    "https://cdn.jsdelivr.net/gh/Arknights-yituliu/frontend-v2-plus@main"
    "/src/static/json/material/composite_table.v2.json"
)
_ITEM_INFO_URL = (
    "https://cdn.jsdelivr.net/gh/Arknights-yituliu/frontend-v2-plus@main"
    "/src/static/json/material/item_info.json"
)

# 资源本/芯片本在 /stage/info 中整类缺席（实测 2026-09-10），
# apCost 与星期开放规则用常量表补齐，口径对齐 MAA StageManager.AddPermanentStages。
# 星期以 0=周一..6=周日 表达；None = 无星期限制（LS-6）。
_PERMANENT_STAGES: tuple[StageMeta, ...] = (
    StageMeta("wk_kc_6", "LS-6", 36, None),
    StageMeta("wk_melee_6", "CE-6", 36, (1, 3, 5, 6)),
    StageMeta("wk_toxic_5", "AP-5", 30, (0, 3, 5, 6)),
    StageMeta("wk_armor_5", "SK-5", 30, (0, 2, 4, 5)),
    StageMeta("wk_fly_5", "CA-5", 30, (1, 2, 4, 6)),
    StageMeta("pro_a_1", "PR-A-1", 18, (0, 3, 4, 6)),
    StageMeta("pro_a_2", "PR-A-2", 36, (0, 3, 4, 6)),
    StageMeta("pro_b_1", "PR-B-1", 18, (0, 1, 4, 5)),
    StageMeta("pro_b_2", "PR-B-2", 36, (0, 1, 4, 5)),
    StageMeta("pro_c_1", "PR-C-1", 18, (2, 3, 5, 6)),
    StageMeta("pro_c_2", "PR-C-2", 36, (2, 3, 5, 6)),
    StageMeta("pro_d_1", "PR-D-1", 18, (1, 2, 5, 6)),
    StageMeta("pro_d_2", "PR-D-2", 36, (1, 2, 5, 6)),
)

# 资源关的固定产出映射：这些材料在掉落矩阵与 MAA stages.json 中都没有
# 掉落条目（固定产出不计入概率掉落统计），但确实由对应资源关产出。
# 映射为"物品 → 资源关 stageId"，直接给出唯一候选，不参与效率排序。
_FIXED_SOURCE_STAGES: dict[str, str] = {
    "4006": "wk_toxic_5",  # 采购凭证 ← AP-5
    "4001": "wk_melee_6",  # 龙门币   ← CE-6
}

# 芯片配方：一图流 composite 表不收芯片条目（实测 2026-09-15 线上表零条），
# 但游戏内双芯片由「对应职业芯片组×2 + 芯片助剂×1」在加工站合成。本地补齐
# 这 8 条边后：双芯片从"不可获取"变为"可合成"，需求自动折算到芯片组（PR
# 芯片关可刷，开放日在 _PERMANENT_STAGES）。
_CHIP_CATALYST_ITEM_ID = "32001"
_CHIP_RECIPES: tuple[Recipe, ...] = tuple(
    Recipe(
        result_item_id=double_id,
        ingredients={group_id: 2, _CHIP_CATALYST_ITEM_ID: 1},
    )
    for group_id, double_id in (
        ("3212", "3213"),  # 先锋
        ("3222", "3223"),  # 近卫
        ("3232", "3233"),  # 重装
        ("3242", "3243"),  # 狙击
        ("3252", "3253"),  # 术师
        ("3262", "3263"),  # 医疗
        ("3272", "3273"),  # 辅助
        ("3282", "3283"),  # 特种
    )
)

# 凭证兑换：芯片助剂在凭证交易所以采购凭证×90 兑换（composite 表同样不收，
# 本地补齐）。采购凭证是固定产出材料，选路层按 0 中性成本当可获取处理，
# 于是助剂折算为"刷 AP-5 攒采购凭证"，理智不可估算；月度限购不在建模范围。
_VOUCHER_RECIPES: tuple[Recipe, ...] = (
    Recipe(result_item_id=_CHIP_CATALYST_ITEM_ID, ingredients={"4006": 90}),
)

# 实测 matrix 0 条直掉关且不在 MAA 排除表（2026-09-11）：模组凭证类属
# "不可获取"，绝不进 PlanList，否则 MaxTimes=∞ 无限刷。龙门币（4001）与
# 采购凭证（4006）不在其中——它们有确定的资源关产出（见 _FIXED_SOURCE_STAGES）。
_UNOBTAINABLE_ITEM_IDS = frozenset(
    {"mod_unlock_token", "mod_update_token_1", "mod_update_token_2"}
)

# 生息演算（RI）是独立模式：MAA 普通 Fight 无法导航到 RI 关卡（且"2字母+
# 数字"代码会被 StageManager 判为过期活动关拒绝），矩阵里的 RI 掉落数据
# 对自动刷取无意义，数据层直接剔除。
_EXCLUDED_STAGE_CODE_PREFIXES = ("RI-",)

# 插曲/别传常驻（一图流 stageType=ACT_PERM，游戏内长期开放，end 是远期占位
# 时间）不在 MAA 常驻关卡表内：StageManager.GetStageInfo 把不在表内、形如
# "2字母+数字"的编号判为过期活动关，库存保持/养成计划随即整条跳过（日志记
# "关卡未开放"）。这类关永远刷不到，会让材料缺口恒存在并持续抑制库存保持，
# 故数据层直接剔除。stageType 缺失时按 stageId 的 _perm 后缀兜底（实测两侧
# 158/158 完全等价）。
_EXCLUDED_STAGE_TYPES = frozenset({"ACT_PERM"})
_EXCLUDED_STAGE_ID_SUFFIXES = ("_perm",)


def _positive_items(raw: Any) -> dict[str, int]:
    """把 {itemId: count} 形态的消耗清洗为正整数字典。"""

    if not isinstance(raw, dict):
        return {}
    items: dict[str, int] = {}
    for item_id, count in raw.items():
        if (
            isinstance(item_id, str)
            and item_id
            and isinstance(count, int)
            and count > 0
        ):
            items[item_id] = count
    return items


def parse_demand_table(raw: Mapping[str, Any]) -> dict[str, tuple[DemandEntry, ...]]:
    """解析干员养成需求表（character_table_simple.v2.json）。

    elite 按相位下标即目标等级；allSkill 为普通技能 2..7 级消耗；
    skills 的 skillLevelUpCost 为专精 1..3 档
    （可能为 null，表示该技能无专精）；equip 的 itemCost 为模组 1..3 档。
    """

    demands: dict[str, tuple[DemandEntry, ...]] = {}
    for char_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        entries: list[DemandEntry] = []

        # 精英化：下标即目标等级（0 为精 0 基础态，无消耗）
        for level, cost in enumerate(entry.get("elite") or [], start=0):
            items = _positive_items(cost)
            if level > 0 and items:
                entries.append(DemandEntry("elite", "", level, items))

        # 普通技能等级为干员共用档位；首项是从 1 升至 2 的消耗。
        skill_costs = entry.get("allSkill")
        for level, cost in enumerate(
            skill_costs[:6] if isinstance(skill_costs, list) else [], start=2
        ):
            items = _positive_items(cost)
            if items:
                entries.append(DemandEntry("skill", "", level, items))

        # 专精：每个技能 1..3 档，skillLevelUpCost 可为 null
        for skill in entry.get("skills") or []:
            if not isinstance(skill, dict) or not skill.get("skillId"):
                continue
            costs = skill.get("skillLevelUpCost")
            if not isinstance(costs, list):
                continue
            for level, cost in enumerate(costs, start=1):
                items = _positive_items(
                    {
                        c.get("id"): c.get("count")
                        for c in cost or []
                        if isinstance(c, dict)
                    }
                )
                if items:
                    entries.append(
                        DemandEntry("mastery", skill["skillId"], level, items)
                    )

        # 模组：每个模组 1..3 档，itemCost 为 {itemId: count} 列表
        for equip in entry.get("equip") or []:
            if not isinstance(equip, dict) or not equip.get("uniEquipId"):
                continue
            costs = equip.get("itemCost")
            if not isinstance(costs, list):
                continue
            for level, cost in enumerate(costs, start=1):
                items = _positive_items(cost)
                if items:
                    entries.append(
                        DemandEntry("module", equip["uniEquipId"], level, items)
                    )

        if entries:
            demands[char_id] = tuple(entries)
    return demands


def parse_drop_matrix(raw: Mapping[str, Any] | list) -> tuple[DropEntry, ...]:
    """解析掉落矩阵；非数字物品 ID（随机材料/家具等占位）直接丢弃。"""

    entries = raw if isinstance(raw, list) else raw.get("matrix", [])
    drops: list[DropEntry] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("itemId")
        stage_id = entry.get("stageId")
        times = entry.get("times")
        quantity = entry.get("quantity")
        if not isinstance(item_id, str) or not item_id.isdigit():
            continue
        if not isinstance(stage_id, str) or not stage_id:
            continue
        if not isinstance(times, (int, float)) or not isinstance(
            quantity, (int, float)
        ):
            continue
        if times <= 0:
            continue
        end = entry.get("end")
        drops.append(
            DropEntry(
                stage_id=stage_id,
                item_id=item_id,
                expected_per_run=quantity / times,
                start_ms=entry.get("start") or 0,
                end_ms=end if isinstance(end, int) else None,
            )
        )
    return tuple(drops)


def parse_stage_info(raw: Mapping[str, Any] | list) -> dict[str, StageMeta]:
    """解析关卡信息并合并 13 关常量表（资源本/芯片本在源数据中整类缺席）。"""

    entries: Any = (
        raw if isinstance(raw, list) else (raw.get("data") or raw.get("stages") or [])
    )
    stages: dict[str, StageMeta] = {
        meta.stage_id: meta
        for meta in (
            StageMeta(
                stage_id=str(entry.get("stageId") or ""),
                stage_code=str(entry.get("stageCode") or ""),
                ap_cost=entry.get("apCost") or 0,
                open_weekdays=None,
            )
            for entry in entries
            if isinstance(entry, dict) and entry.get("stageId")
        )
    }
    for meta in _PERMANENT_STAGES:
        stages.setdefault(meta.stage_id, meta)
    return stages


def parse_recipes(raw: Any) -> tuple[Recipe, ...]:
    """解析合成表为正向合成边（result ← ingredients）。

    composite 表是双形态 schema（实测 2026-09-12）：
    - ``resolve: true``（T2 等低级条目）：分解向——1×pathway 高级材料可
      分解为 count×itemId；逆向即合成边 result=高级, ingredients={低级: count}
      （与 MAA item_index 的 formula 一致）。
    - ``resolve: false``（T5 等高级条目）：合成向——pathway 直接就是配方
      （可多原料），result=itemId, ingredients={pathway: count}。
    """

    ingredients_by_result: dict[str, dict[str, int]] = {}

    def add_recipe(result: Any, ingredients: Mapping[Any, Any]) -> None:
        if not isinstance(result, str) or not result:
            return
        slot = ingredients_by_result.setdefault(result, {})
        for ingredient_id, count in ingredients.items():
            if isinstance(ingredient_id, str) and ingredient_id and count > 0:
                slot[ingredient_id] = count

    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("itemId")
        pathway = entry.get("pathway")
        if not isinstance(item_id, str) or not isinstance(pathway, list):
            continue
        steps = [
            step
            for step in pathway
            if isinstance(step, dict)
            and isinstance(step.get("itemId"), str)
            and isinstance(step.get("count"), int)
            and step["count"] > 0
        ]
        if not steps:
            continue
        if entry.get("resolve"):
            # 分解向：1×steps[k] 高级 → steps[k].count×itemId（逐条建合成边）
            for step in steps:
                add_recipe(step["itemId"], {item_id: step["count"]})
        else:
            # 合成向：count×steps 各项 → 1×itemId
            add_recipe(item_id, {step["itemId"]: step["count"] for step in steps})
    return tuple(
        Recipe(result_item_id=result, ingredients=dict(ingredients))
        for result, ingredients in sorted(ingredients_by_result.items())
    )


def _with_local_recipes(recipes: tuple[Recipe, ...]) -> tuple[Recipe, ...]:
    """合并本地补充配方（一图流未收录的芯片链/凭证兑换）；表中已有同结果条目时以表为准。"""

    existing = {recipe.result_item_id for recipe in recipes}
    local = tuple(
        recipe
        for recipe in (*_CHIP_RECIPES, *_VOUCHER_RECIPES)
        if recipe.result_item_id not in existing
    )
    return recipes + local


def build_material_class(
    demands: Mapping[str, tuple[DemandEntry, ...]],
    drops: tuple[DropEntry, ...],
    stages: Mapping[str, StageMeta],
    recipes: tuple[Recipe, ...],
) -> dict[str, MaterialClass]:
    """按三分类规则预计算物品类别（可直刷 > 可合成折算 > 不可获取）。

    _FIXED_SOURCE_STAGES 中的物品（采购凭证、龙门币）由资源关固定产出，
    与有掉落统计的材料同为可直刷，不因缺掉落条目被判为不可获取。
    """

    farmable = {drop.item_id for drop in drops if drop.stage_id in stages}
    farmable |= {
        item_id
        for item_id, stage_id in _FIXED_SOURCE_STAGES.items()
        if stage_id in stages
    }
    craftable = {recipe.result_item_id for recipe in recipes}
    demand_items = {
        item_id
        for entries in demands.values()
        for entry in entries
        for item_id in entry.items
    }
    classes: dict[str, MaterialClass] = {}
    for item_id in sorted(farmable | craftable | demand_items):
        if item_id in _UNOBTAINABLE_ITEM_IDS:
            classes[item_id] = "unobtainable"
        elif item_id in farmable:
            classes[item_id] = "farmable"
        elif item_id in craftable:
            classes[item_id] = "synthesizable"
        else:
            # 只出现在需求里、既无可直掉关也无配方（如未收录的新材料），按不可获取兜底
            classes[item_id] = "unobtainable"
    return classes


def parse_item_value(raw: Any) -> dict[str, float]:
    """解析一图流物品价值表（itemValue 为理智等价价值，综合效率用）。"""

    values: dict[str, float] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id, value = entry.get("itemId"), entry.get("itemValue")
        if isinstance(item_id, str) and item_id and isinstance(value, (int, float)):
            values[item_id] = float(value)
    return values


def apply_composite(
    stages: Mapping[str, StageMeta],
    drops: tuple[DropEntry, ...],
    item_value: Mapping[str, float],
) -> dict[str, StageMeta]:
    """计算各关卡综合效率（Σ(每次掉落期望×物品价值)/理智，1-7≈100% 基线）。"""

    value_rate: dict[str, float] = {}
    for drop in drops:
        value = item_value.get(drop.item_id)
        if value is None:
            continue
        value_rate[drop.stage_id] = (
            value_rate.get(drop.stage_id, 0.0) + drop.expected_per_run * value
        )
    result: dict[str, StageMeta] = {}
    for stage_id, meta in stages.items():
        ap = meta.ap_cost
        composite = value_rate.get(stage_id, 0.0) / ap if ap > 0 else 0.0
        result[stage_id] = StageMeta(
            stage_id=meta.stage_id,
            stage_code=meta.stage_code,
            ap_cost=meta.ap_cost,
            open_weekdays=meta.open_weekdays,
            composite=round(composite, 4),
        )
    return result


def _excluded_stage_ids(stage_raw: Mapping[str, Any] | list) -> set[str]:
    """MAA 无法导航的关卡 stageId 集（别传常驻；stageType 缺失时按后缀兜底）。"""

    entries: Any = (
        stage_raw
        if isinstance(stage_raw, list)
        else (stage_raw.get("data") or stage_raw.get("stages") or [])
    )
    excluded: set[str] = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        stage_id = str(entry.get("stageId") or "")
        if not stage_id:
            continue
        if entry.get("stageType") in _EXCLUDED_STAGE_TYPES or stage_id.endswith(
            _EXCLUDED_STAGE_ID_SUFFIXES
        ):
            excluded.add(stage_id)
    return excluded


def normalize_dataset(
    demand_raw: Mapping[str, Any],
    matrix_raw: Mapping[str, Any] | list,
    stage_raw: Mapping[str, Any],
    recipe_raw: Any,
    item_info_raw: Any = None,
    *,
    data_version: str,
) -> CultivateDataSet:
    """把五个源数据规范化为内核契约数据集。"""

    demands = parse_demand_table(demand_raw)
    drops = parse_drop_matrix(matrix_raw)
    stages = parse_stage_info(stage_raw)
    recipes = _with_local_recipes(parse_recipes(recipe_raw))
    excluded_stage_ids = _excluded_stage_ids(stage_raw)
    drops = tuple(
        drop
        for drop in drops
        if drop.stage_id not in excluded_stage_ids
        and not (
            drop.stage_id in stages
            and stages[drop.stage_id].stage_code.startswith(
                _EXCLUDED_STAGE_CODE_PREFIXES
            )
        )
    )
    item_value = parse_item_value(item_info_raw) if item_info_raw is not None else {}
    stages = apply_composite(stages, drops, item_value)
    return CultivateDataSet(
        demands=demands,
        drops=drops,
        stages=stages,
        recipes=recipes,
        material_class=build_material_class(demands, drops, stages, recipes),
        fixed_source_stages=dict(_FIXED_SOURCE_STAGES),
        item_value=item_value,
        data_version=data_version,
    )


def dataset_to_json(dataset: CultivateDataSet) -> dict[str, Any]:
    """契约数据集 → JSON 可序列化结构（快照存储用）。"""

    return {
        "schema_version": 2,
        "data_version": dataset.data_version,
        "demands": {
            char_id: [
                {
                    "kind": entry.kind,
                    "target_id": entry.target_id,
                    "level": entry.level,
                    "items": dict(entry.items),
                }
                for entry in entries
            ]
            for char_id, entries in dataset.demands.items()
        },
        "drops": [
            {
                "stage_id": drop.stage_id,
                "item_id": drop.item_id,
                "expected_per_run": drop.expected_per_run,
                "start_ms": drop.start_ms,
                "end_ms": drop.end_ms,
            }
            for drop in dataset.drops
        ],
        "stages": [
            {
                "stage_id": meta.stage_id,
                "stage_code": meta.stage_code,
                "ap_cost": meta.ap_cost,
                "open_weekdays": meta.open_weekdays,
                "composite": meta.composite,
            }
            for meta in dataset.stages.values()
        ],
        "recipes": [
            {"result": recipe.result_item_id, "ingredients": dict(recipe.ingredients)}
            for recipe in dataset.recipes
        ],
        "material_class": dict(dataset.material_class),
        "fixed_source_stages": dict(dataset.fixed_source_stages),
        "item_value": dict(dataset.item_value),
    }


def dataset_from_json(raw: Mapping[str, Any]) -> CultivateDataSet:
    """快照 JSON → 契约数据集。

    快照可能写于剔除规则生效之前，故加载时同样剔除 MAA 无法导航的别传常驻
    关：stageType 不进快照，按 _perm 后缀判定（与 stageType 等价，见上方常量）。
    配方合并本地补充（旧快照缺芯片链）后按当前规则**重算**material_class——
    快照里存的是写入时代的分类结果，直接沿用会让新增配方/规则失效。
    """

    demands = {
        char_id: tuple(
            DemandEntry(
                kind=entry["kind"],
                target_id=entry["target_id"],
                level=entry["level"],
                items=entry["items"],
            )
            for entry in raw.get("demands", {}).get(char_id, [])
        )
        for char_id in raw.get("demands", {})
    }
    drops = tuple(
        DropEntry(
            stage_id=drop["stage_id"],
            item_id=drop["item_id"],
            expected_per_run=drop["expected_per_run"],
            start_ms=drop["start_ms"],
            end_ms=drop["end_ms"],
        )
        for drop in raw.get("drops", [])
        if not drop["stage_id"].endswith(_EXCLUDED_STAGE_ID_SUFFIXES)
    )
    stages = {
        meta["stage_id"]: StageMeta(
            stage_id=meta["stage_id"],
            stage_code=meta["stage_code"],
            ap_cost=meta["ap_cost"],
            open_weekdays=tuple(meta["open_weekdays"])
            if meta["open_weekdays"] is not None
            else None,
            composite=meta.get("composite", 0.0),
        )
        for meta in raw.get("stages", [])
    }
    recipes = _with_local_recipes(
        tuple(
            Recipe(
                result_item_id=recipe["result"],
                ingredients=recipe["ingredients"],
            )
            for recipe in raw.get("recipes", [])
        )
    )
    return CultivateDataSet(
        demands=demands,
        drops=drops,
        stages=stages,
        recipes=recipes,
        material_class=build_material_class(demands, drops, stages, recipes),
        fixed_source_stages=dict(raw.get("fixed_source_stages", {})),
        item_value=dict(raw.get("item_value", {})),
        data_version=raw.get("data_version", ""),
    )


def _max_cost_level(costs: Any, *, start: int) -> int:
    """消耗档位列表里"非空消耗的最高档"：可达档位上限（决策 40）。

    与 parse_demand_table 同判据（非空消耗才成档），保证选择器给出的档位
    一定能在需求层展开；全空/字段缺失返回 0（该维度无可达档位）。
    """

    if not isinstance(costs, list):
        return 0
    reachable = 0
    for level, cost in enumerate(costs, start=start):
        items = _positive_items(
            {
                item.get("id"): item.get("count")
                for item in cost or []
                if isinstance(item, dict)
            }
            if isinstance(cost, list)
            else cost
        )
        if items:
            reachable = max(reachable, level)
    return reachable


def parse_operator_catalog(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """解析干员选择器目录：id/名称/稀有度/职业 + 技能/模组名称（决策 11/38）。

    只取展示字段，不进内核契约（CultivateDataSet 保持中性领域词汇）；
    技能/模组名称供目标编辑行展示（一图流原表自带，R4 起随目录透传）；
    排序为稀有度降序、名称升序。

    同时给出各维度可达档位上限（决策 40）：``maxElite`` 为该干员表中非空
    消耗的最高精英化档（1/2/3★ 与上游缺数据者恒 0，另用 ``dataMissing``
    区分"本就没有精英化"与"上游数据缺失"）；``maxSkillLevel`` 为普通技能等级
    上限；``skills``/``modules`` 每个选项
    带 ``maxLevel``，无可达档位的项不进入目录——选择器不给出刷不到的档位。
    """

    catalog: list[dict[str, Any]] = []
    for char_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not char_id or not isinstance(name, str) or not name:
            continue
        rarity = entry.get("rarity")
        rarity = rarity if isinstance(rarity, int) else 0
        profession = entry.get("profession")
        max_elite = _max_cost_level(entry.get("elite"), start=0)
        skill_costs = entry.get("allSkill")
        max_skill_level = _max_cost_level(
            skill_costs[:6] if isinstance(skill_costs, list) else [], start=2
        )
        skills: list[dict[str, Any]] = []
        # 培养任务按技能序号指定专精，过滤无专精消耗的技能时保留原始序号。
        for skill_index, skill in enumerate(entry.get("skills") or [], start=1):
            if (
                not isinstance(skill, dict)
                or not skill.get("skillId")
                or not skill.get("skillName")
            ):
                continue
            max_level = _max_cost_level(skill.get("skillLevelUpCost"), start=1)
            if max_level <= 0:
                continue
            skills.append(
                {
                    "value": str(skill["skillId"]),
                    "label": str(skill["skillName"]),
                    "maxLevel": max_level,
                    "skillIndex": skill_index,
                }
            )
        modules: list[dict[str, Any]] = []
        for equip in entry.get("equip") or []:
            if (
                not isinstance(equip, dict)
                or not equip.get("uniEquipId")
                or not equip.get("uniEquipName")
            ):
                continue
            max_level = _max_cost_level(equip.get("itemCost"), start=1)
            if max_level <= 0:
                continue
            modules.append(
                {
                    "value": str(equip["uniEquipId"]),
                    "label": (
                        f"{equip['uniEquipName']}（{equip['typeName2']}）"
                        if equip.get("typeName2")
                        else str(equip["uniEquipName"])
                    ),
                    "maxLevel": max_level,
                }
            )
        catalog.append(
            {
                "value": char_id,
                "label": name,
                "rarity": rarity,
                "profession": profession if isinstance(profession, str) else "",
                "maxElite": max_elite,
                "maxSkillLevel": max_skill_level,
                "dataMissing": max_elite == 0 and rarity >= 4,
                "skills": skills,
                "modules": modules,
            }
        )
    catalog.sort(key=lambda item: (-item["rarity"], item["label"]))
    return catalog
