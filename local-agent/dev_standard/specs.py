# -*- coding: utf-8 -*-
"""
开发规范条目注册表（dev-standard · specs.py · 唯一事实源 · Issue #83）
=======================================================================
把「开发规范」从零散的人肉约定，沉淀为**结构化、程序化、可检查**的规范条目。
本文件是**唯一事实源**——各层（检查器/能力/CLI/CI/评审）都从这里读取，不各自取名、
不产生版本差异。

设计原则：
  - 确定性：每条规范绑定一个确定性检查函数（check_type=hard/soft），非 LLM 判断；
  - 三层分级：L1 必做（阻断）/ L2 推荐（警告）/ L3 可选（提示），控制规范粒度；
  - 五类覆盖：structure / code / docs / process / quality；
  - 强制时机（enforce_at）：pre_pr / review / commit / deliver / all——绑定开发阶段；
  - 规范本身不成为"污染残留"：每条规范必须可程序化验证 + 可留痕 + 可追踪。
"""
import os
import re
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


# 级别枚举
LEVEL_L1 = "L1"  # 必做（hard，阻断）
LEVEL_L2 = "L2"  # 推荐（soft，警告）
LEVEL_L3 = "L3"  # 可选（提示）

# 强制时机枚举
AT_PRE_PR = "pre_pr"    # 提 PR 前
AT_REVIEW = "review"    # 评审时
AT_COMMIT = "commit"    # 代码提交时
AT_DELIVER = "deliver"  # 交付时
AT_ALL = "all"          # 全程

# 类别枚举
CAT_STRUCTURE = "structure"  # 结构（模块/PR/解耦）
CAT_CODE = "code"            # 代码（风格/依赖/错误处理）
CAT_DOCS = "docs"            # 文档（留痕/说明）
CAT_PROCESS = "process"      # 流程（声明/版本/进度）
CAT_QUALITY = "quality"      # 质量（自测/范围声明）

VALID_LEVELS = {LEVEL_L1, LEVEL_L2, LEVEL_L3}
VALID_CATEGORIES = {CAT_STRUCTURE, CAT_CODE, CAT_DOCS, CAT_PROCESS, CAT_QUALITY}
VALID_ENFORCE_AT = {AT_PRE_PR, AT_REVIEW, AT_COMMIT, AT_DELIVER, AT_ALL}


def _noop(*args, **kwargs):
    """兜底检查函数（注册表默认指向；实际检查器注入可执行实现）。"""
    return {"ok": True, "details": "noop"}


# ======================================================================
# 规范条目注册表（唯一事实源）
# ======================================================================
# 初始规范集 v0.1（Issue #83）：从现有体系最佳实践沉淀，覆盖 5 类。
# 每条规范：
#   id          稳定编号（S01, S02, ...）
#   title       规范标题（一句可判定）
#   level       L1必做 / L2推荐 / L3可选
#   category    类别
#   check_type  hard阻断 / soft警告
#   description 详细说明（供 agent 理解为何要遵守）
#   enforce_at  强制时机（绑定开发阶段）
#   verify      对应的检查函数名（checker.py 中实现）
STANDARD_SPECS = {
    # ---------------- 结构（structure）----------------
    "S01": {
        "id": "S01",
        "title": "模块独立成 PR，base 一律为 main",
        "level": LEVEL_L1,
        "category": CAT_STRUCTURE,
        "check_type": "hard",
        "description": "每个功能模块独立成 PR，目标分支（base）必须为 main；禁止把新功能模块 base 挂到另一个功能分支/集成分支上，避免耦合冲突。",
        "enforce_at": [AT_PRE_PR, AT_REVIEW],
        "verify": "check_pr_base_main",
    },
    "S02": {
        "id": "S02",
        "title": "按功能域解耦，不挂到他人功能分支",
        "level": LEVEL_L1,
        "category": CAT_STRUCTURE,
        "check_type": "hard",
        "description": "每个模块对应一个独立功能域，模块间只通过稳定接口/数据契约交互，不互相 import 实现、不共享私有内部状态。",
        "enforce_at": [AT_PRE_PR, AT_REVIEW],
        "verify": "check_decoupled",
    },
    "S03": {
        "id": "S03",
        "title": "接口显式化（公开接口 + docstring + 单测）",
        "level": LEVEL_L1,
        "category": CAT_STRUCTURE,
        "check_type": "hard",
        "description": "模块对外能力收口到显式公开接口（__init__.py 导出 + docstring + 单测），便于跨项目调用与参考；接口变更须升版留痕。",
        "enforce_at": [AT_PRE_PR, AT_REVIEW],
        "verify": "check_interface_explicit",
    },
    "S04": {
        "id": "S04",
        "title": "冲突前置规避（merge-tree 校验）",
        "level": LEVEL_L1,
        "category": CAT_STRUCTURE,
        "check_type": "hard",
        "description": "开 PR 前先在本地 merge-tree 校验与 main 无冲突；有冲突先 rebase main 解决再提，禁止带着 conflict 提 PR。",
        "enforce_at": [AT_PRE_PR],
        "verify": "check_no_conflict",
    },
    "S05": {
        "id": "S05",
        "title": "每个 PR 自含测试 + 文档",
        "level": LEVEL_L1,
        "category": CAT_STRUCTURE,
        "check_type": "hard",
        "description": "模块自己的 test_*.sh / 单测 + docs/<MODULE>.md，独立通过信号灯，不依赖他人模块即可运行。",
        "enforce_at": [AT_PRE_PR, AT_REVIEW],
        "verify": "check_has_test_and_docs",
    },
    # ---------------- 代码（code）----------------
    "C01": {
        "id": "C01",
        "title": "错误处理显式（不吞异常）",
        "level": LEVEL_L1,
        "category": CAT_CODE,
        "check_type": "hard",
        "description": "异常必须显式处理并留痕，禁止 bare except 静默吞掉异常；可回溯、不吞异常。",
        "enforce_at": [AT_COMMIT, AT_REVIEW],
        "verify": "check_no_bare_except",
    },
    "C02": {
        "id": "C02",
        "title": "敏感信息不落代码（Token/密码/密钥）",
        "level": LEVEL_L1,
        "category": CAT_CODE,
        "check_type": "hard",
        "description": "严禁在代码/产物/评论中输出 Token、密码、密钥等敏感信息；一律走环境变量/配置注入。",
        "enforce_at": [AT_COMMIT, AT_REVIEW, AT_DELIVER],
        "verify": "check_no_secrets",
    },
    "C03": {
        "id": "C03",
        "title": "不留未引用 import / 死代码",
        "level": LEVEL_L2,
        "category": CAT_CODE,
        "check_type": "soft",
        "description": "移除未使用的 import 与不可达死代码，保持代码整洁可读。",
        "enforce_at": [AT_COMMIT, AT_REVIEW],
        "verify": "check_no_dead_code",
    },
    # ---------------- 文档（docs）----------------
    "D01": {
        "id": "D01",
        "title": "变更必留痕（Issue/PR/提交）",
        "level": LEVEL_L1,
        "category": CAT_DOCS,
        "check_type": "hard",
        "description": "每一步必须真实执行并在 Issue/PR/提交/CI 留下可核验记录，禁止假装执行、禁止无痕产出。",
        "enforce_at": [AT_ALL],
        "verify": "check_traceable",
    },
    # ---------------- 流程（process）----------------
    "P01": {
        "id": "P01",
        "title": "Issue 声明头 + 模块/Agent 双版本管理",
        "level": LEVEL_L1,
        "category": CAT_PROCESS,
        "check_type": "hard",
        "description": "每个 Issue 顶部声明 module/module_version/type/target/update/depends_on；涉及 agent 能力时再加 agent/agent_version；版本以小单位独立升版。",
        "enforce_at": [AT_PRE_PR, AT_REVIEW],
        "verify": "check_issue_declaration",
    },
    "P02": {
        "id": "P02",
        "title": "进度尺标注（goal_meters）",
        "level": LEVEL_L1,
        "category": CAT_PROCESS,
        "check_type": "hard",
        "description": "领取任务后每次推进写一条目标进度尺刻度，以 distance 量化到北极星还剩多远；无刻度视为无效推进。",
        "enforce_at": [AT_ALL],
        "verify": "check_goal_meters",
    },
    # ---------------- 质量（quality）----------------
    "Q01": {
        "id": "Q01",
        "title": "自测结果上报（通过/失败）",
        "level": LEVEL_L1,
        "category": CAT_QUALITY,
        "check_type": "hard",
        "description": "交付时必须上报自测结果（通过/失败），测试信号灯验证；执行-验证分离，dev 不自行裁定'我完成了'。",
        "enforce_at": [AT_DELIVER, AT_REVIEW],
        "verify": "check_self_test_reported",
    },
    "Q02": {
        "id": "Q02",
        "title": "变更范围声明（改了哪些）",
        "level": LEVEL_L2,
        "category": CAT_QUALITY,
        "check_type": "soft",
        "description": "交付时声明本次变更范围（改动文件/模块/影响面），便于评审与回溯。",
        "enforce_at": [AT_DELIVER],
        "verify": "check_scope_declared",
    },
}

# 按级别索引（供分层查询）
SPECS_BY_LEVEL = {}
for _spec in STANDARD_SPECS.values():
    SPECS_BY_LEVEL.setdefault(_spec["level"], []).append(_spec["id"])

# 按类别索引
SPECS_BY_CATEGORY = {}
for _spec in STANDARD_SPECS.values():
    SPECS_BY_CATEGORY.setdefault(_spec["category"], []).append(_spec["id"])

# 按强制时机索引
SPECS_BY_ENFORCE_AT = {}
for _spec in STANDARD_SPECS.values():
    for _stage in _spec["enforce_at"]:
        SPECS_BY_ENFORCE_AT.setdefault(_stage, []).append(_spec["id"])

# 校验函数名 → 实际实现映射（由 checker 填充）
VERIFY_IMPLS = {}


def register_verify(func_name, fn):
    """登记检查函数实现（由 checker.py 在导入时注入）。"""
    VERIFY_IMPLS[func_name] = fn


def get_spec(spec_id):
    """取单条规范详情。未知 spec_id 返回 None。"""
    return STANDARD_SPECS.get(spec_id)


def list_specs(level=None, category=None):
    """列出规范条目（按级别/类别过滤）。"""
    out = []
    for spec in STANDARD_SPECS.values():
        if level and spec["level"] != level:
            continue
        if category and spec["category"] != category:
            continue
        out.append(dict(spec))
    return out


def specs_by_enforce_at(stage):
    """返回某开发阶段的强制规范清单（按该阶段 enforce_at 命中）。"""
    return [STANDARD_SPECS[sid] for sid in SPECS_BY_ENFORCE_AT.get(stage, [])]


def summary():
    """规范注册表概览（二级信息，供人类俯瞰）。"""
    return {
        "total": len(STANDARD_SPECS),
        "by_level": {lv: len(ids) for lv, ids in sorted(SPECS_BY_LEVEL.items())},
        "by_category": {ct: len(ids) for ct, ids in SPECS_BY_CATEGORY.items()},
        "spec_ids": sorted(STANDARD_SPECS.keys()),
    }
