# -*- coding: utf-8 -*-
"""npc-model 信号灯用例（由 test_npc_model.sh 按名字调用）。

放在独立 .py 是为了避免 bash heredoc 里嵌套引号的转义地狱 —— 之前踩过：
外层 bash 双引号吃掉了 python 里的双引号，报错信息还长得像逻辑 bug。
用法：python3 local-agent/tests/npc_model_cases.py <case>
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "local-agent"))

from npc_model import ModelSpec, ModelPolicy, select_model, learn_from_error  # noqa: E402
from npc_model.spec import ModelSpecError  # noqa: E402

CONFIG = os.path.join(ROOT, ".cnb", "npc-models.yml")


def case_prefer_order():
    """prefer 从上到下取第一个可用；黑名单命中即顺延（架构师角色）。"""
    spec = ModelSpec(
        prefer=["qwen4", "hy4"], unavailable=["qwen4"],
        fallback="platform_default", override_env="NPC_MODEL_OVERRIDE", history=[],
        big_model_roles=["架构·总师"])
    p = select_model(spec, env={}, role="架构·总师")
    assert p.model == "hy4", p
    assert p.source == "prefer", p.source
    assert p.npc_options == {"model": "hy4"}, p.npc_options


def case_real_config():
    """真实配置文件可解析；架构师命中大参数，其余角色命中默认档，且都不在黑名单。"""
    spec = ModelSpec.load(CONFIG)
    assert spec.prefer, "prefer 不能为空"
    assert spec.fallback == "platform_default", spec.fallback
    assert spec.big_model_roles, "必须声明吃大模型的角色，否则分层失效"
    assert spec.default_model, "必须声明非架构师角色的默认档"
    big = select_model(spec, env={}, role=spec.big_model_roles[0])
    assert big.model in spec.usable, (big.model, spec.usable)
    other = select_model(spec, env={}, role="架构·开发")
    assert other.model == spec.default_model, other.model
    assert not spec.is_blocked(big.model) and not spec.is_blocked(other.model)


def case_role_gate():
    """★分层闸门：只有名单里的角色吃大参数，其余一律默认档（用户 2026-11-14 要求）。"""
    spec = ModelSpec(
        prefer=["hy4"], unavailable=[], fallback="platform_default",
        override_env="NPC_MODEL_OVERRIDE", history=[],
        default_model="deepseek-v4.1-flash", big_model_roles=["架构·总师"])
    # 架构师 → 大参数
    big = select_model(spec, env={}, role="架构·总师")
    assert big.model == "hy4" and big.source == "prefer", big
    # 其他角色 → 默认档（不蹭大模型）
    for role in ["架构·秘书", "架构·开发", "架构·评审", "CodeBuddy", "市场·销售"]:
        p = select_model(spec, env={}, role=role)
        assert p.model == "deepseek-v4.1-flash", (role, p.model)
        assert p.source == "role_default", (role, p.source)
    # 角色名带不带「架构·」前缀等价（settings 改名不影响闸门）
    assert select_model(spec, env={}, role="总师").model == "hy4"
    # 读不到角色名 → 按非架构师处理，绝不因"拿不准"偷偷抬到贵模型
    assert select_model(spec, env={}).model == "deepseek-v4.1-flash"
    # 角色名从平台注入的 CNB_NPC_NAME 读取（真实触发路径）
    assert select_model(spec, env={"CNB_NPC_NAME": "架构·总师"}).model == "hy4"
    assert select_model(spec, env={"CNB_NPC_NAME": "架构·开发"}).model == "deepseek-v4.1-flash"
    # 显式 role 优先于环境变量（命令行 --role 场景）
    assert select_model(
        spec, env={"CNB_NPC_NAME": "架构·开发"}, role="架构·总师").model == "hy4"
    # 默认档被拉黑 → 不硬塞，退到平台默认
    spec2 = ModelSpec(
        prefer=["hy4"], unavailable=["deepseek-v4.1-flash"],
        fallback="platform_default", override_env="X", history=[],
        default_model="deepseek-v4.1-flash", big_model_roles=["架构·总师"])
    fb = select_model(spec2, env={}, role="架构·开发")
    assert fb.model is None and fb.npc_options == {}, fb
    # 大参数全不可用 → 架构师也不退而求其次用小模型写死，直接平台默认
    spec3 = ModelSpec(
        prefer=["hy4"], unavailable=["hy4"], fallback="platform_default",
        override_env="X", history=[], default_model="deepseek-v4.1-flash",
        big_model_roles=["架构·总师"])
    fb2 = select_model(spec3, env={}, role="架构·总师")
    assert fb2.model is None and fb2.source == "fallback", fb2


def case_fallback_platform_default():
    """候选全不可用 → 平台默认（不写 model），绝不能出现 model: ''。"""
    spec = ModelSpec(prefer=["only-bad"], unavailable=["only-bad"],
                     fallback="platform_default", override_env="X", history=[])
    p = select_model(spec, env={}, role="架构·总师")
    assert p.model is None, p.model
    assert p.use_platform_default is True
    assert p.npc_options == {}, p.npc_options
    assert p.source == "fallback", p.source


def case_override():
    """环境变量覆盖优先于 prefer（不改仓库就能换模型）。"""
    spec = ModelSpec(prefer=["a"], unavailable=[], fallback="platform_default",
                     override_env="NPC_MODEL_OVERRIDE", history=[])
    p = select_model(spec, env={"NPC_MODEL_OVERRIDE": "big-model-9"}, role="架构·开发")
    assert p.model == "big-model-9", p
    assert p.source == "override", p.source
    # 覆盖成黑名单里的 ID 也允许，但必须显式提示风险（人是最终决策者）
    p2 = select_model(
        ModelSpec(prefer=["a"], unavailable=["risky"], fallback="platform_default",
                  override_env="NPC_MODEL_OVERRIDE", history=[]),
        env={"NPC_MODEL_OVERRIDE": "risky"}, role="架构·开发")
    assert p2.model == "risky" and "黑名单" in p2.reason, p2.reason


def case_reject_bad_fallback():
    """fallback 写成具体模型 ID → 确定性拒绝（防把漂移风险搬回来）。"""
    for bad in ["hy4", "deepseek-v4.1-flash", ""]:
        try:
            ModelSpec.from_dict({"prefer": ["hy4"], "fallback": bad})
        except ModelSpecError:
            continue
        raise AssertionError("fallback=%r 应被拒绝" % bad)


def case_reject_empty_prefer():
    try:
        ModelSpec.from_dict({"prefer": [], "fallback": "platform_default"})
    except ModelSpecError:
        return
    raise AssertionError("空 prefer 应被拒绝")


def case_learn():
    """失败日志 → 认出被拒模型 + 给出「该改哪一行」。"""
    spec = ModelSpec.load(CONFIG)
    log = 'npc:go model "glm-9" is not in the optional models list of your organization.'
    hit = learn_from_error(log, spec)
    assert hit and hit["model"] == "glm-9", hit
    assert hit["known"] is False
    assert "unavailable" in hit["hint"], hit["hint"]
    # 已在黑名单里 → 提示不要重复添加
    hit2 = learn_from_error(
        'npc:go model "hy3" is not in the optional models list', spec)
    assert hit2 and hit2["known"] is True, hit2
    # 中文版报错同样识别
    hit3 = learn_from_error('npc:go 模型 "glm-9" 不在当前组织可选模型列表中。', spec)
    assert hit3 and hit3["model"] == "glm-9", hit3
    # 非模型问题不误判
    assert learn_from_error("boom", spec) is None
    assert learn_from_error("", spec) is None


def case_pipeline_wiring():
    """.cnb.yml 走解析结果 + failStages 兜底，且不写死模型 ID。"""
    import re
    src = open(os.path.join(ROOT, ".cnb.yml"), encoding="utf-8").read()
    blk = src[src.index(".npc_task: &npc_task"):src.index("# 看板自动化")]
    assert "scripts/npc-model.sh resolve" in blk, "未接模型解析"
    # 分层闸门必须由解析层接管：.cnb.yml 里不许自己按角色写模型分支
    assert "CNB_NPC_NAME" in blk, "未说明角色闸门判据"
    assert "model: $NPC_MODEL" in blk, "未使用解析出的模型"
    assert "failStages" in blk, "缺兜底路径"
    assert 'role: "架构·秘书"' in blk, "角色丢失"
    # 兜底那一跳必须不写 model（否则等于没有兜底）
    fb = blk[blk.index("failStages"):]
    fb = fb[fb.index("npc go (fallback)"):]
    assert "model:" not in fb, "兜底跳不应写 model（应走平台默认）"
    # 全文不得有生效的写死模型
    lines = [l for l in src.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    bad = [l.strip() for l in lines
           if re.match(r"^\s*model:\s*\S+", l) and "NPC_MODEL" not in l]
    assert not bad, "仍写死模型：%s" % bad


def case_role_config():
    """真实配置：只有架构师在名单里，默认档是 deepseek-v4.1-flash（用户指定）。"""
    import yaml
    data = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    roles = data.get("big_model_roles") or []
    assert "架构·总师" in roles, roles
    # 大模型只给架构师——其他架构/市场角色不许混进名单（分层的前提）
    assert len(roles) == 1, "只有架构师角色吃大模型，多一个都是溢价：%s" % roles
    assert data.get("default_model") == "deepseek-v4.1-flash", data.get("default_model")


CASES = {
    "prefer_order": case_prefer_order,
    "role_gate": case_role_gate,
    "role_config": case_role_config,
    "real_config": case_real_config,
    "fallback_platform_default": case_fallback_platform_default,
    "override": case_override,
    "reject_bad_fallback": case_reject_bad_fallback,
    "reject_empty_prefer": case_reject_empty_prefer,
    "learn": case_learn,
    "pipeline_wiring": case_pipeline_wiring,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        print("case 必须是：%s" % ", ".join(sorted(CASES)))
        sys.exit(2)
    CASES[sys.argv[1]]()
    print("ok")
