# -*- coding: utf-8 -*-
"""
规模伸缩层 · 统一调度引擎（engine）
====================================
把「规模声明 + 前置流程区分 + 角色插件 + 消息总线 + 状态分片 + 并发池」
整合为一条可伸缩的规模化流水线。

核心链路（对应用户诉求）：
  1. `--spec '{"team_size": N, "levels": L, "mode": ...}'` 声明团队规模；
  2. `profile.route()` 做**前置流程区分**（不同位置走不同流程模板）；
  3. `plugin.merged_registry()` 加载内置 + 插件角色（灵活增减）；
  4. `broker` 建消息总线，`store` 按 agent 分片建状态；
  5. `pool.run_wave()` 真并行执行 DAG 波次（并发度= spec.concurrency）；
  6. 汇总交付报告 + 规模资源评估。

scale 流水线是既有 orchestrator 的**规模化增强**：小规模（< LOCAL_CAP）可
单机跑通全链路；大规模（上百/上千/2500）则给出分布式后端建议并模拟并发调度，
证明「消息传递 + 分工 + 状态」在架构上可承载。
"""
import json
import time

from . import broker, store, pool, spec, profile, plugin, prescale

# 数据底座（数据架构升级）：规模流水线的信息互通/内容存档/进度/任务 落到数据库承载
DATA_ENABLED = True
try:
    from ..data import admin as data_admin
    from ..data import db as data_db
except Exception:  # noqa: BLE001
    try:
        from data import admin as data_admin
        from data import db as data_db
    except Exception:  # noqa: BLE001
        DATA_ENABLED = False


def preflight(spec_obj, direct_role=None):
    """前置检查：校验规模声明 + 强制入口 + 规模预设 + 前置路由 + 资源评估。

    参数:
      spec_obj: 规模声明
      direct_role: 若显式 @ 了某角色（绕过秘书），传入以校验强制入口
    返回 dict: { spec, route, entry_guard, prescale, resource, topology }
    """
    s = spec.normalize(spec_obj)
    r = profile.route(s.get("profile", "default"))
    # 强制入口护栏：需求必须先经「架构·秘书」接收/路由留痕，不可跳过
    guard = profile.guard_entry(s.get("profile", "default"), direct_role=direct_role)
    # 规模预设：澄清阶段先按体量预设，作为经理增量修正的基准锚点
    pre = prescale.prescale(
        s.get("req", "") or s.get("request", "") or "",
        kind=r["profile"],
    )
    est = spec.resource_estimate(s)
    topo = spec.build_topology(s)
    return {
        "spec": s,
        "route": r,
        "entry_guard": guard,
        "prescale": pre,
        "resource": est,
        "topology": topo,
        "leaf_agents": spec.leaf_count(topo),
    }


def run_scaled(req, spec_obj=None, concurrency_override=None, verbose=True):
    """运行一条规模化流水线。

    参数:
      req: 用户需求文本
      spec_obj: 规模声明 dict/str（可选）
      concurrency_override: 覆盖并发度（用于测试压力）
    返回:
      dict 交付报告（含资源评估、路由、分片卡、消息总线统计、波次执行结果）
    """
    t0 = time.time()
    s = spec.normalize(spec_obj or {})
    if concurrency_override:
        s["concurrency"] = concurrency_override
    s["req"] = req  # 把需求文本挂到 spec，供 prescale 使用

    # 1. 前置流程区分 + 强制入口护栏（不可跳过秘书）
    route = profile.route(s.get("profile", "default"))
    guard = profile.guard_entry(s.get("profile", "default"), direct_role=s.get("direct_role"))
    # 1b. 规模预设（澄清阶段基准锚点）——第 1 次定团队规模
    pre = prescale.prescale(req, kind=route["profile"])
    # 1c. 架构明确后，架构·经理按架构做增量修正——第 2 次定团队规模
    #     基于澄清预设 scale_factor 增量调整，不做从零规划（adjust_by_architect）
    arch_factor = float(s.get("arch_scale_factor", 1.0))
    risk_override = s.get("risk_override") or None
    pre_adj = prescale.adjust_by_architect(pre, {
        "scale_factor": arch_factor,
        "risk_override": risk_override,
    })
    # 实际团队规模 = max(用户声明, 经理增量修正) —— 修正值作为最低基准锚点
    adjusted_size = max(s["team_size"], pre_adj["team_size"])
    if adjusted_size != s["team_size"]:
        s["team_size"] = adjusted_size
        s["concurrency"] = max(1, adjusted_size) if s["concurrency"] == arch_factor or s.get("_auto_conc") else s["concurrency"]
    # 2. 加载角色（内置 + 插件）
    reg = plugin.merged_registry()
    # 按 profile / spec 过滤角色
    role_names = plugin.filter_by_spec(list(reg.keys()), s.get("roles", []))
    if verbose:
        print(f"[scale] 前置路由: {route['description']}")
        print(f"[scale] 强制入口护栏: {guard['message']}")
        print(f"[scale] 第1次定规模(澄清预设): {pre['team_size']} 人 / {pre['collab_plan']} / 风险 {pre['risk_level']} (source={pre['source']})")
        print(f"[scale] 第2次定规模(经理增量修正): {pre_adj['team_size']} 人 / 风险 {pre_adj['risk_level']} "
              f"(adjusted_by_architect={pre_adj.get('adjusted_by_architect')}, scale_factor={arch_factor})")
        print(f"[scale] 实际团队规模(取max): {s['team_size']} 个 agent, "
              f"分工层级 {s['levels']}, 并发 {s['concurrency']}")
        print(f"[scale] 可用角色 {len(role_names)} 个: {role_names[:8]}{'...' if len(role_names)>8 else ''}")

    # 3. 建消息总线 + 状态分片（按团队规模预分片）
    cards = {}
    for i in range(s["team_size"]):
        cid = f"agent_{i}"
        cards[cid] = store.new_card(cid, role="agent", req=req)
    if verbose:
        print(f"[scale] 已建 {len(cards)} 张分片状态卡 (state cards)")

    # 3b. 数据底座：把规模流水线的 agent 档案/任务登记进数据库（内容存档/信息互通）
    if DATA_ENABLED:
        try:
            data_admin.init()
            data_admin.archive(
                f"scale_run_{int(time.time()*1000)}",
                "milestone",
                f"规模流水线 {req}",
                {"team_size": s["team_size"], "levels": s["levels"],
                 "profile": route["profile"], "backend": data_db.backend()},
                "scale-engine",
            )
            data_admin.record_event("data_admin", "scale_launch",
                                    {"team_size": s["team_size"], "concurrency": s["concurrency"]})
            for i in range(s["team_size"]):
                data_admin.register_agent(
                    f"agent_{i}", role="agent",
                    group_id=f"g{i % max(1, s['levels'])}",
                    status="in_progress",
                    spec={"req": req},
                )
                data_admin.deliver(
                    f"agent_{i}", "team.round1",
                    {"req": req, "assignee": f"agent_{i}"},
                )
                data_admin.assign_task(
                    f"scale_task_{i}",
                    f"规模流水线子任务 {i}",
                    assignee=f"agent_{i}",
                    status="in_progress",
                )
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"[scale] ⚠ 数据底座写入跳过: {e}")

    # 4. 生成团队拓扑（分工层级）
    topo = spec.build_topology(s)
    leaf = spec.leaf_count(topo)
    est = spec.resource_estimate(s)

    # 5. 模拟并发波次执行（用并发池真并行）
    #    每个 agent 各自消费消息 → 产出 → 上报
    def _agent_task(agent_id):
        # 模拟一个 agent 的完整回合：收消息 → 处理 → 回写状态 → 发消息
        broker.subscribe(agent_id, "team.round1")
        # 模拟收到一条任务消息
        broker.deliver(agent_id, "task", {"req": req, "assignee": agent_id})
        msg = broker.consume(agent_id)
        out = (
            f"[agent {agent_id}] 处理消息 "
            f"{msg['msg_id'] if msg else 'none'} → 输出片段"
        )
        store.append_log(agent_id, f"processed: {out}")
        return out

    tasks = [(cid, (lambda aid=cid: _agent_task(aid))) for cid in cards]
    wres = pool.run_concurrent(tasks, max_workers=s["concurrency"])
    broker_stats = broker.stats()

    # 数据底座：消费消息 + 记录进度事件 + 生成聚合指标快照（进度统计/看板）
    data_report = None
    if DATA_ENABLED:
        try:
            for i in range(s["team_size"]):
                cid = f"agent_{i}"
                data_admin.consume(cid)                 # 消费消息管线
                data_admin.record_event(cid, "processed", {"done": True})
                data_admin.update_task(f"scale_task_{i}", "done")
            stats = data_admin.snapshot_stats()
            data_report = {
                "backend": data_db.backend(),
                "agents": data_admin.progress_report()["agents"],
                "stats": stats,
            }
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"[scale] ⚠ 数据底座统计跳过: {e}")

    report = {
        "req": req,
        "scaled": True,
        "spec": s,
        "route": route,
        "entry_guard": guard,
        "prescale": pre,
        "prescale_adjusted": pre_adj,   # 第 2 次定团队规模（经理按架构增量修正）
        "scale_twice": {
            "first": {"team_size": pre["team_size"], "collab": pre["collab_plan"],
                       "risk": pre["risk_level"], "stage": "澄清预设"},
            "second": {"team_size": pre_adj["team_size"], "risk": pre_adj["risk_level"],
                        "stage": "经理按架构增量修正", "adjusted": pre_adj.get("adjusted_by_architect")},
            "final_team_size": s["team_size"],
        },
        "resource": est,
        "topology": {"leaf_agents": leaf},
        "cards_created": len(cards),
        "execution": {
            "concurrency": s["concurrency"],
            "results": wres["results"],
            "errors": wres["errors"],
        },
        "broker_stats": broker_stats,
        "data": data_report,       # 数据底座（数据库承载）报告
        "elapsed_sec": round(time.time() - t0, 3),
    }
    if verbose:
        print(f"[scale] 并发执行完成: {len(wres['results'])} 成功, "
              f"{len(wres['errors'])} 失败, 耗时 {report['elapsed_sec']}s")
        print(f"[scale] 消息总线: {broker_stats}")
        if est["warning"]:
            print(f"[scale] ⚠ 规模提示: {est['warning']}")
    return report


def run_scale_wave_demo(wave_nodes, concurrency=None):
    """演示一个 DAG 波次的真并行执行。

    参数: wave_nodes: list[(node_id, fn)]
    """
    return pool.run_wave(wave_nodes, max_workers=concurrency)


def to_json(report):
    return json.dumps(report, ensure_ascii=False, indent=2, default=str)
