#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 Agent · 入口（替代云端 @ 触发）
====================================
用法：
  # 一键编排完整团队流水线（产品→架构→分工→协同→测试→交付）
  python local-agent/run.py --pipeline full --req "我要做一个XX系统"

  # 触发单个角色（对应云端 @角色）
  python local-agent/run.py --role 架构·总师 --req "对XX做架构设计"

  # 列出团队角色
  python local-agent/run.py --list-roles

  # 从接力卡续跑（对应云端 [打断] 续跑）
  python local-agent/run.py --resume

  # 指定模型后端（默认自动：OPENAI_API_KEY → cli_fallback 占位）
  python local-agent/run.py --pipeline full --req "XX" --backend cli_fallback

  # 清空接力卡
  python local-agent/run.py --clear
"""
import argparse
import json
import os
import sys

# 允许直接以脚本运行（python run.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestrator
import relay
from roles import list_roles

# 规模伸缩层（架构升级核心）
from scale import engine, spec, profile, prescale, plugin


def main():
    parser = argparse.ArgumentParser(
        description="本地 Agent 团队入口（替代云端 @ 触发）"
    )
    parser.add_argument("--pipeline", help="运行团队流水线，如 full")
    parser.add_argument("--role", help="触发单个角色，如 架构·总师")
    parser.add_argument("--req", help="用户需求/请求")
    parser.add_argument("--backend", default=None, help="模型后端：openai_compat / cli_fallback")
    parser.add_argument("--list-roles", action="store_true", help="列出团队角色（含插件）")
    parser.add_argument("--resume", action="store_true", help="从接力卡续跑")
    parser.add_argument("--clear", action="store_true", help="清空接力卡")
    # ---- 架构升级新增入口 ----
    parser.add_argument("--scale", action="store_true", help="运行规模化流水线（scale 引擎）")
    parser.add_argument("--spec", default=None,
                        help='团队规模声明 JSON，如 \'{"team_size": 2500, "levels": 3, "mode": "harness"}\'')
    parser.add_argument("--profile", default=None, help="前置流程模板：default/company/harness/acquisition/support")
    parser.add_argument("--list-profiles", action="store_true", help="列出前置流程模板")
    parser.add_argument("--concurrency", type=int, default=None, help="覆盖并发度（压测）")
    # ---- 规模预设 + 强制入口（测试关键发现修复）----
    parser.add_argument("--prescale", action="store_true", help="对需求做规模预设（澄清阶段基准锚点）")
    parser.add_argument("--complexity", default=None, help="显式指定复杂度带：simple/medium/complex")
    # ---- 融合路由接线（打通"规模→拓扑→执行"断点）----
    parser.add_argument("--no-fusion", action="store_true", help="回退老行为：不走融合路由，硬编码 team.yaml dag")
    parser.add_argument("--topo", default=None, help="显式指定拓扑：linear/dag/event/hybrid/scatter/agile/prefix（绕过规模评估）")
    parser.add_argument("--subtasks", type=int, default=None, help="显式子任务数（融合路由规模信号）")

    parser.add_argument("--guard-entry", action="store_true", help="校验强制入口（是否必须经架构·秘书）")
    parser.add_argument("--direct-role", default=None, help="显式 @ 的角色（用于校验是否跳过秘书）")
    parser.add_argument("--prescale-records", action="store_true", help="列出规模预设留痕记录")
    args = parser.parse_args()

    if args.prescale_records:
        recs = prescale.prescale_records()
        if not recs:
            print("（暂无规模预设记录）")
        else:
            print(f"规模预设留痕记录（共 {len(recs)} 条）：")
            for key, rec in recs.items():
                p = rec.get("preset", {})
                print(f"  - [{rec.get('kind')}] {rec.get('req_key')}")
                print(f"      → team_size={p.get('team_size')} collab={p.get('collab_plan')} "
                      f"risk={p.get('risk_level')} source={p.get('source')}")
        return 0

    if args.guard_entry:
        if not args.req:
            parser.error("--guard-entry 需要 --req 需求文本")
        r = profile.guard_entry(
            (spec.parse(args.spec) if args.spec else {}).get("profile", "default"),
            direct_role=args.direct_role,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["ok"] else 2

    if args.prescale:
        if not args.req:
            parser.error("--prescale 需要 --req 需求文本")
        kind = (spec.parse(args.spec) if args.spec else {}).get("profile", "default")
        pre = prescale.prescale(args.req, kind=kind, complexity_hint=args.complexity)
        print(prescale.to_json(pre))
        return 0

    if args.list_profiles:
        print("前置流程模板（不同位置不同流程）：")
        for p in profile.list_profiles():
            print(f"  - {p}: {profile.describe(p)}")
        return 0

    if args.list_roles:
        # 合并内置 + 插件角色（灵活增减）
        reg = plugin.merged_registry()
        print(f"团队角色（共 {len(reg)} 个，含插件）：")
        for r in reg:
            print(f"  - {r}")
        return 0

    if args.clear:
        relay.clear()
        print("已清空接力卡")
        return 0

    if args.scale:
        # 规模化流水线：声明团队大小/分工层级/并发度 + 前置流程区分
        spec_obj = {}
        if args.spec:
            spec_obj = spec.parse(args.spec)
        if args.profile:
            spec_obj["profile"] = args.profile
        if not args.req:
            parser.error("--scale 需要 --req 需求文本")
        report = engine.run_scaled(
            args.req,
            spec_obj=spec_obj,
            concurrency_override=args.concurrency,
            verbose=True,
        )
        print("\n===== 规模化交付报告 =====")
        print(engine.to_json(report))
        return 0

    if args.resume:
        card = relay.load()
        if not card:
            print("无接力卡可续跑，请先 --pipeline 或 --role 启动。")
            return 1
        print(f"[续跑] 从接力卡当前进度续跑：{card.get('current_progress')}")
        # 简化：续跑 = 重新跑完整流水线（保留 req）
        report = orchestrator.run_pipeline(card["req"], backend=args.backend)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if not args.req:
        parser.error("--req 必填（除非使用 --list-roles/--list-profiles/--resume/--clear）")

    if args.pipeline:
        report = orchestrator.run_pipeline(
            args.req,
            backend=args.backend,
            use_fusion=not args.no_fusion,
            force_topology=args.topo,
            complexity=args.complexity,
            subtasks=args.subtasks,
        )
        print("\n===== 交付报告 =====")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.role:
        result = orchestrator.run_role(args.role, args.req, backend=args.backend)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error("请指定 --pipeline 或 --role")


if __name__ == "__main__":
    sys.exit(main())
