# -*- coding: utf-8 -*-
"""
memory.cli —— 经验记忆库命令行入口

用法：
  python -m memory.cli add --role 架构·开发 --text "..." [--backend lancedb]
  python -m memory.cli trigger --text "写一个登录接口"
  python -m memory.cli list [--backend lancedb] [--limit 20]
  python -m memory.cli count [--backend lancedb]
"""

import argparse
import sys

from .schema import MemoryRecord, now_iso, hash_embedding
from .store import MemoryStore
from .triggers import SemanticTriggerEngine


def _build_store(args):
    return MemoryStore(backend=args.backend,
                       path=getattr(args, "path", "./.memory"),
                       export_dir=getattr(args, "export_dir", "./.memory-cloud"))


def cmd_add(args):
    store = _build_store(args)
    rec = MemoryRecord(
        id=args.id or f"role:{args.role}:{store.count() + 1:06d}",
        role=args.role,
        category=args.category,
        text=args.text,
        vector=hash_embedding(args.text),
        meta={"source": args.source or "cli"},
        created_at=now_iso(),
    )
    n = store.add([rec])
    store.close()
    print(f"✅ 已写入 {n} 条到 {args.backend} 后端（id={rec.id}）")


def cmd_trigger(args):
    eng = SemanticTriggerEngine(threshold=args.threshold)
    store = None
    if args.with_memory:
        store = _build_store(args)
        result = eng.trigger_with_memory(args.text, store, top_k=args.top_k)
        store.close()
    else:
        result = eng.trigger(args.text)
    print(f"触发方式: {result['method']}")
    print(f"命中角色: {result['role'] or '（未命中）'}")
    print(f"相似度:   {result['score']}")
    print(f"置信度:   {result['confidence']}")
    for h in result.get("memory_hits", []):
        print(f"  · 记忆参考 [{h['id']}] {h['text'][:40]}... (score={h['score']})")


def cmd_list(args):
    store = _build_store(args)
    # LanceDB 无直接列表接口，用 count 兜底；cloud 返回内存记录
    n = store.count()
    print(f"{args.backend} 后端当前共 {n} 条记忆。")
    store.close()


def cmd_count(args):
    store = _build_store(args)
    print(store.count())
    store.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="memory", description="架构师经验记忆库")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_backend_args(sp, default_backend="lancedb"):
        sp.add_argument("--backend", choices=["lancedb", "cloud", "dual"],
                        default=default_backend)
        sp.add_argument("--path", default="./.memory")
        sp.add_argument("--export-dir", default="./.memory-cloud")

    sp_add = sub.add_parser("add")
    add_backend_args(sp_add)
    sp_add.add_argument("--role", required=True)
    sp_add.add_argument("--text", required=True)
    sp_add.add_argument("--category", default="experience")
    sp_add.add_argument("--id", default="")
    sp_add.add_argument("--source", default="")

    sp_tr = sub.add_parser("trigger")
    sp_tr.add_argument("--text", required=True)
    sp_tr.add_argument("--threshold", type=float, default=0.10)
    sp_tr.add_argument("--with-memory", action="store_true")
    sp_tr.add_argument("--top-k", type=int, default=3)
    add_backend_args(sp_tr)

    sp_ls = sub.add_parser("list")
    add_backend_args(sp_ls)

    sp_cnt = sub.add_parser("count")
    add_backend_args(sp_cnt)

    args = p.parse_args(argv)
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main(sys.argv[1:])
