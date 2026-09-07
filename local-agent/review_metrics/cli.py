# -*- coding: utf-8 -*-
"""
有效性度量模型 · CLI（MCP 管线）
================================
供脚本 / CI / 人肉调用程序化度量（不依赖 AI 对话）。

用法：
  python -m review_metrics.cli dims
  python -m review_metrics.cli spec
  python -m review_metrics.cli measure '<obs-json>'      # 单次观测度量+留痕
  python -m review_metrics.cli judge '<obs-list-json>'   # 多次归并+达标判定
  python -m review_metrics.cli trace [limit]
"""
import json
import sys


def _usage():
    print(__doc__)
    sys.exit(1)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        return _usage()
    cmd = argv[0]
    from review_metrics import spec, engine
    if cmd == "dims":
        print(json.dumps({"dims": spec.valid_dims()}, ensure_ascii=False))
    elif cmd == "spec":
        print(json.dumps(spec.summary(), ensure_ascii=False, indent=2))
    elif cmd == "measure":
        if len(argv) < 2:
            return _usage()
        obs = json.loads(argv[1])
        n = engine.normalize_profile(obs)
        r = engine.aggregate([n])
        j = engine.judge(r)
        tid = engine.trace(obs, r)
        print(json.dumps({"trace_id": tid, "normalized": n,
                          "result": r, "verdict": j}, ensure_ascii=False, indent=2))
    elif cmd == "judge":
        if len(argv) < 2:
            return _usage()
        obs_list = json.loads(argv[1])
        r = engine.aggregate(obs_list)
        j = engine.judge(r)
        print(json.dumps({"result": r, "verdict": j}, ensure_ascii=False, indent=2))
    elif cmd == "trace":
        limit = int(argv[1]) if len(argv) > 1 else 20
        print(json.dumps(engine.trace_recent(limit=limit), ensure_ascii=False, indent=2))
    else:
        return _usage()
    return 0


if __name__ == "__main__":
    sys.exit(main())
