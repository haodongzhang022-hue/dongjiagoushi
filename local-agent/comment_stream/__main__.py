# -*- coding: utf-8 -*-
"""comment_stream CLI：python -m comment_stream --kind pulls --number 161"""
import argparse
import json

from .reader import read_comments, comment_meta


def main(argv=None):
    p = argparse.ArgumentParser(prog="comment_stream",
                                description="统一读评论流入口（默认读全量，Issue #166）")
    p.add_argument("--kind", default="issues", choices=["issue", "issues", "pull", "pulls"])
    p.add_argument("--number", type=int, required=True, help="Issue/PR 编号")
    p.add_argument("--repo", default=None, help="org/repo（缺省取 CNB_REPO）")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--days", type=float, default=None, help="只看最近 N 天（时间窗过滤）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    a = p.parse_args(argv)

    result = read_comments(kind=a.kind, number=a.number, repo=a.repo,
                           page_size=a.page_size)
    if a.days:
        from datetime import datetime, timedelta
        keep = []
        for c in result["comments"]:
            ts = (c.get("created_at") or "").replace("Z", "+00:00")
            try:
                if datetime.fromisoformat(ts) >= datetime.now().astimezone() - timedelta(days=a.days):
                    keep.append(c)
            except ValueError:
                keep.append(c)
        result = dict(result, comments=keep, count=len(keep))

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    meta = comment_meta(result)
    print("评论流 %s#%s：%d 条 / %d 页 / page_size=%s / complete=%s"
          % (result["kind"], result["number"], meta["count"], meta["pages"],
             meta["page_size"], meta["complete"]))
    for c in result["comments"]:
        body = (c.get("body") or "").replace("\n", " ")[:100]
        print("  [%s] %s: %s" % (c.get("created_at", ""), c.get("author", "?"), body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
