# -*- coding: utf-8 -*-
"""
本地 Agent · 编排引擎（orchestrator）
======================================
把"用户提交请求 → 团队流水线 → 交付"串成自动编排。

- 支持 **DAG 工作流**（`pipeline.dag`）：节点依赖 + 并行波次调度（graph.py）；
- 支持 **分形扩展**（fractal.py）：开发任务按规模拆为多小组并行，小组长整合；
- 回退到线性 `pipeline.steps`（不配 dag 时，兼容旧调用）；
- 输出写入接力卡；支持回转（revert_to）与打断（--resume 续跑）。
"""
import os
import sys

import yaml

import relay
from graph import DagEngine, build_dag_from_steps
from llm import get_backend
from roles import get_role

TEAM_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.yaml")


def load_team():
    with open(TEAM_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _step_label(node):
    return f"[{node['id']}] {node['role']}：{node['action']}"

def _run_one(role, req, llm, card, node):
    """执行单个角色节点，返回输出。"""
    user_input = req
    try:
        output = role.run(llm, user_input)
    except Exception as e:
        output = f"[执行异常] {e}"
    card["output"] = output
    relay.log(card, f"节点 {node['id']} 完成")
    return output


def _fractal_develop(plan, req, llm, card, team):
    """分形扩展：把开发任务拆为多小组并行，各小组开发后由小组长整合测试。

    当前为结构骨架实现：真实任务拆解依赖架构·经理的输出与 LLM；
    此处生成分形计划并逐小组执行，输出整合摘要（占位后端下不伪造真实代码）。
    """
    import fractal

    plan_text = fractal.describe_plan(plan)
    relay.log(card, f"[分形] 开发按规模拆为 {plan['team_count']} 个小组并行")

    dev_role = get_role("架构·开发")
    lead_role = get_role("架构·小组长")
    lines = [plan_text]
    for t in plan["teams"]:
        sub_req = f"{req}\n（分形小组 {t['team_id']}，任务：{t['tasks']}）"
        out = dev_role.run(llm, sub_req) if dev_role else f"[无开发角色] {t['team_id']}"
        lines.append(f"--- {t['team_id']} 开发输出 ---\n{out}")
        # 小组长对单小组做整合（测试+整合摘要）
        if lead_role:
            integ = lead_role.run(
                llm, f"整合并测试小组 {t['team_id']} 的交付：{out}"
            )
            lines.append(f"--- {t['team_id']} 整合 ---\n{integ}")
    card["output"] = "\n".join(lines)
    relay.log(card, "[分形] 多小组开发+整合完成，统一向上交付")
    return card["output"]


def run_pipeline(req, backend=None, llm=None, use_dag=True):
    """执行团队流水线到交付。默认走 DAG 调度；use_dag=False 回退线性。

    返回交付报告 dict。
    """
    team = load_team()
    llm = llm or get_backend(backend)

    card = relay.new_card(req, first_step="secretary", first_role="架构·秘书")
    report = {"req": req, "dag": False, "steps": []}

    # ---- 构建 DAG ----
    if use_dag and "dag" in team.get("pipeline", {}):
        dag = DagEngine(
            name=team["pipeline"]["name"],
            description=team["pipeline"].get("description", ""),
            nodes=team["pipeline"]["dag"]["nodes"],
        )
        ok, err = dag.validate()
        if not ok:
            card["status"] = "blocked"
            card["output"] = f"[DAG 校验失败] {err}"
            relay.save(card)
            report["steps"].append({"step": "dag_validate", "role": "编排引擎",
                                    "output": card["output"]})
            return report
        report["dag"] = True
        waves = dag.waves()
        report["waves"] = [list(w) for w in waves]

        for wave in waves:
            # 同一波次内的节点可并行（此处逐个执行，真实并行交由调度器/多线程）
            for nid in wave:
                nd = dag.nodes[nid]
                card["step"] = nid
                card["role"] = nd["role"]
                card["status"] = "in_progress"
                card["current_progress"] = _step_label(nd)
                relay.save(card)
                print(f"\n▶ [DAG波次] {_step_label(nd)}")

                # 分形开发节点
                if nd.get("fractal") and nd["fractal"].get("enabled") and nd["role"] == "架构·开发":
                    import fractal

                    # 用架构·经理的任务拆解估算任务数（占位：以 req 长度/估算）
                    n_tasks = _estimate_tasks(req)
                    plan = fractal.build_fractal_plan(
                        [f"task{i}" for i in range(n_tasks)],
                        max_per_team=nd["fractal"].get("max_per_team", 4),
                    )
                    out = _fractal_develop(plan, req, llm, card, team)
                elif nd["role"] == "编排引擎":
                    card["output"] = f"交付完成：{req}"
                    card["status"] = "done"
                    relay.save(card)
                    out = card["output"]
                else:
                    role = get_role(nd["role"])
                    if role is None:
                        out = f"[错误] 未注册角色 {nd['role']}"
                        card["status"] = "blocked"
                    else:
                        out = _run_one(role, card.get("input", req), llm, card, nd)

                card["output"] = out
                card["input"] = out  # 下游消费本环输出
                relay.save(card)
                report["steps"].append(
                    {"step": nid, "role": nd["role"], "output": out}
                )
        card["status"] = "done"
        card["output"] = f"交付完成：{req}"
        relay.save(card)
        return report

    # ---- 回退：线性 steps（兼容旧配置/旧调用）----
    steps = team["pipeline"]["steps"]
    dag = build_dag_from_steps(steps)
    waves = dag.waves()
    report["steps"] = []
    for wave in waves:
        for nid in wave:
            nd = dag.nodes[nid]
            step = next(s for s in steps if s["step"] == nid)
            card["step"] = nid
            card["role"] = nd["role"]
            card["status"] = "in_progress"
            card["current_progress"] = _step_label(nd)
            relay.save(card)
            print(f"\n▶ {_step_label(nd)}")

            if nd["role"] == "编排引擎":
                card["output"] = f"交付完成：{req}"
                card["status"] = "done"
                relay.save(card)
                out = card["output"]
            else:
                role = get_role(nd["role"])
                if role is None:
                    out = f"[错误] 未注册角色 {nd['role']}"
                    card["status"] = "blocked"
                else:
                    out = _run_one(role, card.get("input", req), llm, card, nd)

            card["output"] = out
            card["input"] = out
            relay.save(card)
            report["steps"].append(
                {"step": nid, "role": nd["role"], "output": out}
            )
    card["status"] = "done"
    card["output"] = f"交付完成：{req}"
    relay.save(card)
    return report


def _estimate_tasks(req):
    """占位：根据需求文本长度粗略估算任务数（真实值应由架构·经理拆解输出）。"""
    base = max(1, len(req) // 40)
    return min(base, 12)


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
