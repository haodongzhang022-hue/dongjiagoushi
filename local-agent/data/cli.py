# -*- coding: utf-8 -*-
"""
数据管理层 · 命令行入口（cli）
================================
提供对数据底座的操作命令，供数据管理员/运维/测试调用。

用法示例：
    python local-agent/data/cli.py init                    # 建表 + 登记数据管理员
    python local-agent/data/cli.py agent add --id a0 --role 架构·开发
    python local-agent/data/cli.py archive --id m1 --kind milestone --title 里程碑 --content 内容
    python local-agent/data/cli.py stats                    # 生成聚合指标快照
    python local-agent/data/cli.py report                   # 进度统计报告
    python local-agent/data/cli.py msg post --topic team.r1 --payload '{"n":1}'
    python local-agent/data/cli.py task add --id t1 --title 实现登录 --assignee 架构·开发
    python local-agent/data/cli.py tables                   # 查看当前表
    python local-agent/data/cli.py status                   # 后端 / 事务态（诊断）
"""
import argparse
import json
import sys
import os

# 使 `from data import ...` 可导入（把本文件上级目录加进 path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import admin, db, migrate, schema  # noqa: E402


def main():
    p = argparse.ArgumentParser(prog="data-cli", description="数据管理层命令行")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建表 + 登记数据管理员")
    sub.add_parser("tables", help="查看当前表")
    sub.add_parser("status", help="查看后端 / 当前线程事务态（诊断用）")
    pm = sub.add_parser("migrate", help="执行库结构/数据迁移（幂等，可重放）")
    pm.add_argument("--dry-run", action="store_true",
                    help="只报告待迁移项，不落任何写（大库迁移前先看代价）")

    # agent
    pa = sub.add_parser("agent", help="agent 档案")
    pa_sub = pa.add_subparsers(dest="action", required=True)
    pa_add = pa_sub.add_parser("add")
    pa_add.add_argument("--id", required=True)
    pa_add.add_argument("--role", default="agent")
    pa_add.add_argument("--group", default="")

    # archive
    pa = sub.add_parser("archive")
    pa.add_argument("--id", required=True)
    pa.add_argument("--kind", default="artifact")
    pa.add_argument("--title", default="")
    pa.add_argument("--content", default="")
    pa.add_argument("--source", default="cli")

    # stats / report
    sub.add_parser("stats", help="生成聚合指标快照")
    sub.add_parser("report", help="进度统计报告")

    # msg
    pm = sub.add_parser("msg")
    pm_sub = pm.add_subparsers(dest="action", required=True)
    pm_post = pm_sub.add_parser("post")
    pm_post.add_argument("--topic", required=True)
    pm_post.add_argument("--payload", default="{}")
    pm_post.add_argument("--from", dest="from_agent", default="cli")

    # task
    pt = sub.add_parser("task")
    pt_sub = pt.add_subparsers(dest="action", required=True)
    pt_add = pt_sub.add_parser("add")
    pt_add.add_argument("--id", required=True)
    pt_add.add_argument("--title", default="")
    pt_add.add_argument("--assignee", default="")
    pt_add.add_argument("--depends", default="")

    args = p.parse_args()

    if args.cmd == "init":
        print(json.dumps(admin.init(), ensure_ascii=False, indent=2))
    elif args.cmd == "migrate":
        print(json.dumps(migrate.migrate(dry_run=args.dry_run), ensure_ascii=False, indent=2))
    elif args.cmd == "tables":
        print("tables:", schema.list_tables())
    elif args.cmd == "status":
        # 事务态用只读探针 db.is_in_tx()（不看 conn.in_transaction：sqlite 常态为 True）
        print(json.dumps({
            "backend": db.backend(),
            "is_remote": db.is_remote(),
            "in_transaction": db.is_in_tx(),
            "tx_depth": db.tx_depth(),
            "db_path": db.DB_PATH if not db.is_remote() else "(remote)",
        }, ensure_ascii=False, indent=2))
    elif args.cmd == "agent":
        admin.register_agent(args.id, args.role, args.group)
        print(f"✅ 已登记 agent: {args.id} (role={args.role})")
    elif args.cmd == "archive":
        admin.archive(args.id, args.kind, args.title, args.content, args.source)
        print(f"✅ 已归档: {args.id} (kind={args.kind})")
    elif args.cmd == "stats":
        print(json.dumps(admin.snapshot_stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "report":
        print(json.dumps(admin.progress_report(), ensure_ascii=False, indent=2))
    elif args.cmd == "msg":
        payload = json.loads(args.payload)
        m = admin.post_message(args.topic, payload, args.from_agent)
        print(f"✅ 消息入队: {m['msg_id']} topic={args.topic}")
    elif args.cmd == "task":
        admin.assign_task(args.id, args.title, args.assignee, args.depends)
        print(f"✅ 已登记任务: {args.id} (assignee={args.assignee})")


if __name__ == "__main__":
    main()
