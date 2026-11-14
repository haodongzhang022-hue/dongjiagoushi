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
    """prefer 从上到下取第一个可用；黑名单命中即顺延。"""
    spec = ModelSpec(
        prefer=["qwen4", "hy4"], unavailable=["qwen4"],
        fallback="platform_default", override_env="NPC_MODEL_OVERRIDE", history=[])
    p = select_model(spec, env={})
    assert p.model == "hy4", p
    assert p.source == "prefer", p.source
    assert p.npc_options == {"model": "hy4"}, p.npc_options


def case_real_config():
    """真实配置文件可解析，且选出的模型不在黑名单里。"""
    spec = ModelSpec.load(CONFIG)
    assert spec.prefer, "prefer 不能为空"
    assert spec.fallback == "platform_default", spec.fallback
    p = select_model(spec, env={})
    assert p.model in spec.usable, (p.model, spec.usable)
    assert not spec.is_blocked(p.model), p.model


def case_fallback_platform_default():
    """候选全不可用 → 平台默认（不写 model），绝不能出现 model: ''。"""
    spec = ModelSpec(prefer=["only-bad"], unavailable=["only-bad"],
                     fallback="platform_default", override_env="X", history=[])
    p = select_model(spec, env={})
    assert p.model is None, p.model
    assert p.use_platform_default is True
    assert p.npc_options == {}, p.npc_options
    assert p.source == "fallback", p.source


def case_override():
    """环境变量覆盖优先于 prefer（不改仓库就能换模型）。"""
    spec = ModelSpec(prefer=["a"], unavailable=[], fallback="platform_default",
                     override_env="NPC_MODEL_OVERRIDE", history=[])
    p = select_model(spec, env={"NPC_MODEL_OVERRIDE": "big-model-9"})
    assert p.model == "big-model-9", p
    assert p.source == "override", p.source
    # 覆盖成黑名单里的 ID 也允许，但必须显式提示风险（人是最终决策者）
    p2 = select_model(
        ModelSpec(prefer=["a"], unavailable=["risky"], fallback="platform_default",
                  override_env="NPC_MODEL_OVERRIDE", history=[]),
        env={"NPC_MODEL_OVERRIDE": "risky"})
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


CASES = {
    "prefer_order": case_prefer_order,
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
