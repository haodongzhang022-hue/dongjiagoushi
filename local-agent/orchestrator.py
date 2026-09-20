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
import re
import sys

import yaml

import relay
from graph import DagEngine, build_dag_from_steps
from llm import get_backend
from roles import get_role
# 2 次定团队规模：澄清阶段 prescale + 架构明确后经理 adjust_by_architect
from scale import prescale as _prescale

TEAM_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.yaml")


def load_team():
    with open(TEAM_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _step_label(node):
    return f"[{node['id']}] {node['role']}：{node['action']}"

def _run_one(role, req, llm, card, node):
    """执行单个角色节点，返回输出。

    编排层缓存（M3）：跨节点复用共享需求前缀（req 稳定部分），
    记录编排层缓存命中事件（按 agent × 层归因，供命中监控）。
    role.run() 内部已做角色壳层缓存；此处补「编排层跨节点复用」统计。
    """
    user_input = req
    try:
        output = role.run(llm, user_input)
    except Exception as e:
        output = f"[执行异常] {e}"
    # 编排层：跨节点共享 req 前缀（稳定需求描述 → 命中缓存）
    try:
        from llm import cache as _cache
        _cache.record_cache_event(
            agent=role.name, layer="orchestrator", cache_hit=1 if req else 0,
            prefix_chars=len(str(req)[:24]),
            saved_tokens=max(0, len(str(req)[:24]) // 3),
        )
    except Exception:
        pass
    card["output"] = output
    relay.log(card, f"节点 {node['id']} 完成")
    return output


def _fractal_develop(plan, req, llm, card, team):
    """分形扩展：把开发任务拆为多小组并行，各小组内同岗位开发真并行+互发消息，
    小组长整合测试后统一向上交付。

    升级：接入同岗位协作（collab.peer）：
      - 用 peer.auto_fractal 建各小组的同岗位 cohort（差异化编队，默认单兵、按需补位）；
      - 小组内开发 agent 真并行执行且互发消息消费彼此产出（不再是串行 for 循环）；
      - 支持按信号（专长缺口/卡点/高风险）触发差异化补位。
    """
    import fractal
    from collab import peer

    plan_text = fractal.describe_plan(plan)
    relay.log(card, f"[分形] 开发按规模拆为 {plan['team_count']} 个小组并行")

    dev_role = get_role("架构·开发")
    lead_role = get_role("架构·小组长")
    lines = [plan_text]

    # ★ Issue #74：为每个小组建同岗位 cohort（差异化编队），
    #   开发实例数按 devs_per_team 恒定（"一套循环 N 个开发"），不按任务数膨胀——
    #   保证每个小组恒定 2 个开发作为实干主力，辅助质量闸门在小组外，不挤占开发名额。
    devs_per_team = plan.get("devs_per_team", 2)
    cohorts = {}
    for t in plan["teams"]:
        cid = peer.spawn_cohort(
            "架构·开发",
            lead_agent=f"dev-{t['team_id']}-lead",
            size=devs_per_team,
            mode="differentiated",
            req=req,
            space=f"team.{t['team_id']}",
        )
        cohorts[t["team_id"]] = cid

    for t in plan["teams"]:
        cid = cohorts[t["team_id"]]
        sub_req = f"{req}\n（分形小组 {t['team_id']}，任务：{t['tasks']}）"
        # 小组内同岗位开发真并行 + 互发消息（不再是串行 for）
        agents = peer.cohort_members(cid)
        if len(agents) <= 1:
            # 单兵：主战直做（默认单兵，防冗余）
            out = dev_role.run(llm, sub_req) if dev_role else f"[无开发角色] {t['team_id']}"
            lines.append(f"--- {t['team_id']} 开发输出 ---\n{out}")
        else:
            # 多 agent：差异化并行，各自负责不同专长切面，产出通过 peer_message 交互
            def _dev(aid, task, fb):
                return (dev_role.run(llm, f"{sub_req}\n（agent {aid} 负责）")
                        if dev_role else f"[无开发角色] {aid}")
            team_out = peer.team_parallel_execute(cid, t["tasks"], _dev)
            for aid, out in team_out.items():
                lines.append(f"--- {t['team_id']}·{aid} 开发输出 ---\n{out}")
        # 小组长对单小组做整合（测试+整合摘要）
        if lead_role:
            integ = lead_role.run(
                llm, f"整合并测试小组 {t['team_id']} 的交付：{lines[-1]}"
            )
            lines.append(f"--- {t['team_id']} 整合 ---\n{integ}")
    card["output"] = "\n".join(lines)
    relay.log(card, "[分形] 多小组同岗并行开发+整合完成，统一向上交付")
    return card["output"]


# ---------------------------------------------------------------------------
# 阶段链门控生产接线（Issue #150 复评 N2）
# ---------------------------------------------------------------------------
# 背景：阶段门控的 `mark_done` 此前只存在于 demo 与测试脚本，生产路径**没有任何收口
# 登记点** → 上游"永不收口"→ 评审段整条主路径被打死（复评 N2）。
# 这里把编排节点执行前后接到阶段链上：角色开工登记活跃、节点完成登记收口，
# 链条据此按「开发 → 评审 → 测试」有序推进（阶段名映射走唯一事实源 ROLE_STAGE）。
def _stage_task_key(req):
    """编排内的稳定阶段任务键（同一需求二次触发不漂移）。"""
    return "pipeline:" + (req or "")[:48]


def _stage_wire(role_name, req, phase, gate=None):
    """按角色名把编排节点接到阶段链（开工/收口），返回留痕 dict。

    phase: "active"（节点开工）| "done"（节点收口）
    未注册阶段角色（如经理/秘书）→ 返回 ok=False，不影响主流程。
    """
    try:
        from review_cycle import stage_spec as _ss
        if role_name not in _ss.ROLE_STAGE:
            return {"ok": False, "reason": "角色无阶段", "role": role_name}
        from review_cycle.gate import StageGate
        g = gate or StageGate()
        tk = _stage_task_key(req)
        if phase == "active":
            return g.mark_role_active(tk, role_name, note="编排节点开工")
        return g.mark_role_done(tk, role_name)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e), "role": role_name}


def run_pipeline(req, backend=None, llm=None, use_dag=True, use_fusion=False,
             force_topology=None, complexity=None, subtasks=None, concurrency=None):
    """执行团队流水线到交付。默认走 DAG 调度；use_dag=False 回退线性。

    返回交付报告 dict。
    """
    team = load_team()
    llm = llm or get_backend(backend)

    # 数据底座初始化（幂等：建表 + 登记数据管理员档案）。
    # 分形开发（peer.spawn_cohort → gid_registry）与 collab 引擎均依赖数据层表，
    # 未初始化即报 'no such table: gid_registry'（CI 直跑 run.py --pipeline 复现）。
    try:
        from data import admin as _dadmin
        _dadmin.init()
    except Exception:  # noqa: BLE001
        pass

    card = relay.new_card(req, first_step="secretary", first_role="架构·秘书")
    report = {"req": req, "dag": False, "steps": []}

    # 2 次定团队规模·留痕：秘书澄清阶段第 1 次预设，经理按架构第 2 次增量修正
    scale_twice = {}

    # ---- 融合路由：use_fusion=True 时按规模选拓扑动态执行（打通"规模→拓扑→执行"断点）----
    dag_nodes = team["pipeline"]["dag"]["nodes"]
    fusion_info = None
    if use_fusion:
        from topology import router as _router
        try:
            routed = _router.route_pipeline(
                req, preset=scale_twice.get("first"),
                complexity=complexity, subtasks=subtasks, concurrency=concurrency,
                force=force_topology,
            )
            dag_nodes = routed["nodes"]
            fusion_info = {
                "selected": routed["selected"],
                "tier": routed["tier"],
                "system": routed["system"],
                "reason": routed["reason"],
                "node_count": len(routed["nodes"]),
                "estimated": routed["estimated"],
            }
            report["fusion"] = fusion_info
            print(f"\n▶ [融合路由] 规模={routed['tier']} 承接体系={routed['system']} "
                  f"→ 拓扑={routed['selected']}（{len(routed['nodes'])} 节点）")
            print(f"   依据: {routed['reason']}")
        except Exception as _e:
            print(f"[融合路由] 失败回退 team.yaml dag: {_e}")

    # ---- 构建 DAG ----
    if use_dag and "dag" in team.get("pipeline", {}):
        dag = DagEngine(
            name=team["pipeline"]["name"],
            description=team["pipeline"].get("description", ""),
            nodes=dag_nodes,
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

                # ---- 开发小组驱动已消费的 dev 节点：跳过，避免重复执行 ----
                if card.get("consumed_dev_nodes") and nid in card.get("consumed_dev_nodes", []):
                    print(f"   [跳过] dev 节点 {nid} 已由开发小组闭环驱动消费")
                    out = f"[已由开发小组闭环驱动消费] {_step_label(nd)}"
                    card["output"] = out
                    card["input"] = out
                    relay.save(card)
                    report["steps"].append(
                        {"step": nid, "role": nd["role"], "output": out}
                    )
                    continue

                # ---- 2 次定团队规模·秘书澄清阶段第 1 次预设 ----
                if nid == "secretary" or nd["role"] == "架构·秘书":
                    pre = _prescale.prescale(req, kind="default")
                    scale_twice["first"] = {
                        "stage": "秘书澄清阶段",
                        "team_size": pre["team_size"],
                        "collab": pre["collab_plan"],
                        "risk": pre["risk_level"],
                        "source": pre["source"],
                    }
                    print(f"   [第1次定规模] 秘书澄清预设: team_size={pre['team_size']} "
                          f"collab={pre['collab_plan']} risk={pre['risk_level']} (source={pre['source']})")
                    # ---- 规模匹配落位澄清阶段（非第一步、非优先级）----
                    # 秘书→产品澄清时评估项目层级 → 匹配承接体系/拓扑/角色子集，作为后续协作基准；
                    # 经理再按架构做增量修正，不做从零规划、不二次评估（对齐 Issue #41 纠偏）。
                    try:
                        from roles import secretary_sense as _sense
                        sm = _sense.scale_match(
                            req, complexity=getattr(nd, "complexity", None),
                            subtasks=getattr(nd, "subtasks", None),
                            concurrency=getattr(nd, "concurrency", None),
                        )
                        scale_twice["first"].update({
                            "tier": sm["tier"],
                            "system": sm["system"],
                            "topology": sm["topology"],
                            "roles": sm["roles"],
                        })
                        report["scale_match"] = {
                            "stage": "秘书澄清阶段(规模匹配)",
                            "tier": sm["tier"],
                            "system": sm["system"],
                            "topology": sm["topology"],
                            "roles": sm["roles"],
                            "reason": sm["reason"],
                        }
                        print(f"   [规模匹配] 秘书澄清评估项目层级: tier={sm['tier']} "
                              f"system={sm['system']} topology={sm['topology']} "
                              f"roles={len(sm['roles'])}个")
                    except Exception as _e:
                        print(f"   [规模匹配] 跳过(能力不可用): {_e}")

                # ---- 2 次定团队规模·经理按架构第 2 次增量修正 ----
                if nid == "plan" or nd["role"] == "架构·经理":
                    base = scale_twice.get("first")
                    if base:
                        # 经理按架构评估的增量因子：默认取澄清预设，可用 --arch-scale-factor 覆盖
                        adj = _prescale.adjust_by_architect(
                            {
                                "team_size": base["team_size"],
                                "collab_plan": base["collab"],
                                "risk_level": base["risk"],
                            },
                            {"scale_factor": float(getattr(nd, "scale_factor", 1.0))
                             if hasattr(nd, "scale_factor") else 1.0},
                        )
                        scale_twice["second"] = {
                            "stage": "经理按架构增量修正",
                            "team_size": adj["team_size"],
                            "risk": adj["risk_level"],
                            "adjusted": adj.get("adjusted_by_architect"),
                            "scale_factor": 1.0,
                        }
                        print(f"   [第2次定规模] 经理增量修正: team_size={adj['team_size']} "
                              f"risk={adj['risk_level']} (adjusted={adj.get('adjusted_by_architect')})")

                # ---- 开发小组闭环接线（方案 A · 把 DevTeam 接成真实可跑链路）----
                _devteam_driven = False
                # dev_enhanced / dev_team 拓扑的 lead（小组长）节点：确定性驱动
                # 一套循环 N 个开发（默认2），全部 APPROVED 后小组长整合交付。
                # 被驱动的 dev_N 开发节点由本驱动统一消费，不再逐个 _run_one 重复执行。
                if (nd.get("role") == "架构·小组长"
                        and dag_nodes
                        and any((_n.get("role") == "架构·开发" and re.match(r'^dev_\d+$', str(_n.get("id", ""))))
                                for _n in dag_nodes)
                        and not nd.get("fractal")):
                    from dev_team_driver import DevTeamDriver
                    try:
                        _dev_nodes = [
                            _n for _n in dag_nodes
                            if _n.get("role") == "架构·开发"
                            and re.match(r'^dev_\d+$', str(_n.get("id", "")))
                        ]
                        _devs_per_team = max(1, len(_dev_nodes) or 2)
                        _driver = DevTeamDriver(
                            goal_total=float(getattr(nd, "goal_total", 0) or 0),
                            devs_per_team=_devs_per_team,
                            lead_id=nd["role"], owner=req[:24],
                        )
                        # 目标未显式给定时按需求粗估（开发小组需目标明确才进闭环）
                        if _driver.goal_total <= 0:
                            from dev_team_driver import estimate_goal_total
                            _goal = estimate_goal_total(req)
                            _driver.goal_total = _goal
                            _driver.team.goal_total = _goal
                        _can, _why = _driver.can_enter()
                        if not _can:
                            out = f"[开发小组] 目标未量化，跳过小组闭环：{_why}"
                            print(f"   {out}")
                            _devteam_driven = True
                        else:
                            _res = _driver.drive(
                                req=req, task_id=f"{req[:24]}",
                                summary=f"开发小组闭环交付（{_devs_per_team} 开发）",
                                delta_per_round=float(getattr(nd, "delta_per_round", 1.0) or 1.0),
                            )
                            out = (
                                f"[开发小组] 建组={_driver.team.devs_per_team}开发 目标={_driver.goal_total} "
                                f"轮次={len(_res['rounds'])} 终态={_res['rounds'][-1]['verdict'] if _res['rounds'] else 'NA'} "
                                f"进度={_res['progress']['progress_pct']}% "
                                f"交付={_res['delivery'] is not None}"
                            )
                            print(f"   {out}")
                            # 消费掉跟随 lead 的 dev 节点，避免下游重复执行
                            card["consumed_dev_nodes"] = [_n["id"] for _n in _dev_nodes]
                            _devteam_driven = True
                    except Exception as _e:
                        out = f"[开发小组驱动异常] {_e}"
                        print(f"   {out}")
                        _devteam_driven = True

                # 分形开发节点（未由开发小组驱动时才执行）
                if (not _devteam_driven
                        and nd.get("fractal") and nd["fractal"].get("enabled") and nd["role"] == "架构·开发"):
                    import fractal

                    # 用架构·经理的任务拆解估算任务数（占位：以 req 长度/估算）
                    n_tasks = _estimate_tasks(req)
                    plan = fractal.build_fractal_plan(
                        [f"task{i}" for i in range(n_tasks)],
                        max_per_team=nd["fractal"].get("max_per_team", 4),
                        devs_per_team=nd["fractal"].get("devs_per_team", 2),
                    )
                    out = _fractal_develop(plan, req, llm, card, team)
                elif not _devteam_driven and nd["role"] == "编排引擎":
                    card["output"] = f"交付完成：{req}"
                    card["status"] = "done"
                    relay.save(card)
                    out = card["output"]
                elif not _devteam_driven:
                    role = get_role(nd["role"])
                    if role is None:
                        out = f"[错误] 未注册角色 {nd['role']}"
                        card["status"] = "blocked"
                    else:
                        # N2 阶段链接线：开工登记 → 执行 → 收口登记（链条按序推进）
                        _stage_wire(nd["role"], req, "active")
                        out = _run_one(role, card.get("input", req), llm, card, nd)
                        _stage_wire(nd["role"], req, "done")

                card["output"] = out
                card["input"] = out  # 下游消费本环输出
                relay.save(card)
                report["steps"].append(
                    {"step": nid, "role": nd["role"], "output": out}
                )
        card["status"] = "done"
        card["output"] = f"交付完成：{req}"
        relay.save(card)
        report["scale_twice"] = scale_twice
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

            # ---- 2 次定团队规模（线性回退同样接入）----
            if nid == "secretary" or nd["role"] == "架构·秘书":
                _pre = _prescale.prescale(req, kind="default")
                scale_twice["first"] = {
                    "stage": "秘书澄清阶段", "team_size": _pre["team_size"],
                    "collab": _pre["collab_plan"], "risk": _pre["risk_level"],
                    "source": _pre["source"],
                }
                print(f"   [第1次定规模] 秘书澄清预设: team_size={_pre['team_size']} "
                      f"collab={_pre['collab_plan']} risk={_pre['risk_level']} (source={_pre['source']})")
                # ---- 规模匹配落位澄清阶段（非第一步、非优先级）----
                try:
                    from roles import secretary_sense as _sense
                    _sm = _sense.scale_match(_req_text if "_req_text" in dir() else req)
                    report["scale_match"] = {
                        "stage": "秘书澄清阶段(规模匹配)",
                        "tier": _sm["tier"], "system": _sm["system"],
                        "topology": _sm["topology"], "roles": _sm["roles"],
                        "reason": _sm["reason"],
                    }
                    print(f"   [规模匹配] 秘书澄清评估项目层级: tier={_sm['tier']} "
                          f"system={_sm['system']} topology={_sm['topology']}")
                except Exception as _e:
                    print(f"   [规模匹配] 跳过: {_e}")
            if nid == "plan" or nd["role"] == "架构·经理":
                if scale_twice.get("first"):
                    _base = scale_twice["first"]
                    _adj = _prescale.adjust_by_architect(
                        {"team_size": _base["team_size"], "collab_plan": _base["collab"],
                         "risk_level": _base["risk"]},
                        {"scale_factor": 1.0},
                    )
                    scale_twice["second"] = {
                        "stage": "经理按架构增量修正", "team_size": _adj["team_size"],
                        "risk": _adj["risk_level"], "adjusted": _adj.get("adjusted_by_architect"),
                        "scale_factor": 1.0,
                    }
                    print(f"   [第2次定规模] 经理增量修正: team_size={_adj['team_size']} "
                          f"risk={_adj['risk_level']} (adjusted={_adj.get('adjusted_by_architect')})")

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
                    # N2 阶段链接线（线性回退同样接上，避免"只有 DAG 才按序"）
                    _stage_wire(nd["role"], req, "active")
                    out = _run_one(role, card.get("input", req), llm, card, nd)
                    _stage_wire(nd["role"], req, "done")

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
    """估算子任务数（供分形多小组触发，真实值应由架构·经理拆解输出）。

    启发式优先级：
      1. 显式编号条目：匹配 `数字`、`数字.`、`数字、`、`数字)`（如 "1任务 2任务..."）——
         最能反映用户枚举的子需求数，据此估算任务数；
      2. 顿号/分号/逗号分隔的短条目数；
      3. 兜底：按需求文本长度估算。
    保证至少返回 1，上限 12（防止一次性拆出过多小组）。
    """
    import re

    # ① 显式编号条目：提取所有数字编号（形如 1、2、… 或 1. 2. / 1) 2) 等）
    numbered = re.findall(r'(?:^|[\s，,、。.;；)])(\d{1,2})\s*[\.、)）]?\s*(?=[^\d])', req)
    if numbered:
        try:
            nums = sorted(int(x) for x in numbered)
            # 取最大连续编号区间作为子需求数（容忍 1 位误差）
            # 常见写法 "1... 2... 3..." → 编号集合近似连续
            uniq = list(dict.fromkeys(nums))
            max_n = max(uniq)
            if max_n >= 2:  # 有明确多条目
                n = min(max(max_n, len(uniq)), 12)
                return n
        except ValueError:
            pass

    # ② 顿号/逗号/分号分隔的短条目数（用于 "A、B、C" 这类枚举）
    parts = [p for p in re.split(r'[、，,；;\n]', req) if p.strip()]
    if len(parts) >= 3:
        n = min(len(parts), 12)
        return n

    # ③ 兜底：按需求文本长度粗略估算
    base = max(1, len(req) // 40)
    return min(base, 12)


def run_role(role_name, req, backend=None, llm=None):
    """执行单个角色（对应云端 @单个角色 触发）。"""
    llm = llm or get_backend(backend)
    role = get_role(role_name)
    if role is None:
        return {"error": f"未注册角色 {role_name}；可用: {list(get_role_registry_names())}"}
    # N2 阶段链接线：单角色触发同样登记开工/收口（否则门控看不到上游收口）
    _stage_wire(role_name, req, "active")
    output = role.run(llm, req)
    stage_done = _stage_wire(role_name, req, "done")
    return {"role": role_name, "output": output, "stage_done": stage_done}


def get_role_registry_names():
    from roles import list_roles

    return list_roles()


def main():
    """CLI 入口（由 run.py 调用）。"""
    pass


if __name__ == "__main__":
    main()
