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


def main():
    parser = argparse.ArgumentParser(
        description="本地 Agent 团队入口（替代云端 @ 触发）"
    )
    parser.add_argument("--pipeline", help="运行团队流水线，如 full")
    parser.add_argument("--role", help="触发单个角色，如 架构·总师")
    parser.add_argument("--req", help="用户需求/请求")
    parser.add_argument("--backend", default=None, help="模型后端：openai_compat / cli_fallback")
    parser.add_argument("--list-roles", action="store_true", help="列出团队角色")
    parser.add_argument("--resume", action="store_true", help="从接力卡续跑")
    parser.add_argument("--clear", action="store_true", help="清空接力卡")
    args = parser.parse_args()

    if args.list_roles:
        print("团队角色：")
        for r in list_roles():
            print(f"  - {r}")
        return 0

    if args.clear:
        relay.clear()
        print("已清空接力卡")
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
        parser.error("--req 必填（除非使用 --list-roles/--resume/--clear）")

    if args.pipeline:
        report = orchestrator.run_pipeline(args.req, backend=args.backend)
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
