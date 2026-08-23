# -*- coding: utf-8 -*-
"""
本地 Agent · 编排引擎（orchestrator）
======================================
把"用户提交请求 → 团队流水线 → 交付"串成自动编排。

- 读取 team.yaml 的 pipeline.steps；
- 逐步调度对应角色（roles/<module>）执行，输出写入接力卡；
- 支持回转（revert_to）与打断（--resume 续跑）；
- 结果汇总为交付报告。
"""
import os
import sys

import yaml

import relay
from llm import get_backend
from roles import get_role

TEAM_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.yaml")


def load_team():
    with open(TEAM_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _step_label(step):
    return f"[{step['step']}] {step['role']}：{step['action']}"


def run_pipeline(req, backend=None, llm=None):
    """执行完整团队流水线到交付。返回交付报告 dict。"""
    team = load_team()
    steps = team["pipeline"]["steps"]
    llm = llm or get_backend(backend)

    card = relay.new_card(req, first_step=steps[0]["step"], first_role=steps[0]["role"])
    report = {"req": req, "steps": []}

    idx = 0
    while idx < len(steps):
        step = steps[idx]
        role_name = step["role"]
        card["step"] = step["step"]
        card["role"] = role_name
        card["status"] = "in_progress"
        card["current_progress"] = _step_label(step)
        card["next_step"] = steps[idx + 1]["step"] if idx + 1 < len(steps) else ""
        relay.save(card)

        print(f"\n▶ 步骤 {idx+1}/{len(steps)}: {_step_label(step)}")

        if role_name == "编排引擎":
            # 最后一环：汇总交付
            card["output"] = f"交付完成：{card['req']}"
            card["status"] = "done"
            relay.save(card)
            report["steps"].append(
                {"step": step["step"], "role": role_name, "output": card["output"]}
            )
            idx += 1
            continue

        role = get_role(role_name)
        if role is None:
            card["output"] = f"[错误] 未注册角色 {role_name}"
            card["status"] = "blocked"
            relay.save(card)
            report["steps"].append({"step": step["step"], "role": role_name,
                                    "output": card["output"]})
            idx += 1
            continue

        # 输入 = 上一环输出（或原始需求）
        user_input = card.get("input", card["req"])
        try:
            output = role.run(llm, user_input)
        except Exception as e:
            output = f"[执行异常] {e}"
        card["output"] = output
        relay.log(card, f"步骤 {step['step']} 完成")
        relay.save(card)
        report["steps"].append({"step": step["step"], "role": role_name,
                                "output": output})
        # 下一环的输入 = 本环输出
        if idx + 1 < len(steps):
            card["input"] = output
        idx += 1

    card["status"] = "done"
    card["output"] = f"交付完成：{card['req']}"
    relay.save(card)
    return report


def run_role(role_name, req, backend=None, llm=None):
    """执行单个角色（对应云端 @单个角色 触发）。"""
    llm = llm or get_backend(backend)
    role = get_role(role_name)
    if role is None:
        return {"error": f"未注册角色 {role_name}；可用: {list(get_role_registry_names())}"}
    output = role.run(llm, req)
    return {"role": role_name, "output": output}


def get_role_registry_names():
    from roles import list_roles

    return list_roles()


def main():
    """CLI 入口（由 run.py 调用）。"""
    pass


if __name__ == "__main__":
    main()
