#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评论流统一入口信号灯（Issue #166 · 默认全量读，杜绝静默截断）

信号灯：
  1. 默认全量：评论数 > 默认页大小 时，入口一次读全（含元信息）
  2. 防退化断言：裸调（不带分页）在同一夹具上必然读不全 → RED
  3. 元信息：count / pages / has_more / complete / truncated 可核验
  4. has_receipt 读取侧消费：读到尾部回执才判 received；读不全时显式 degraded
  5. 参数/异常：kind 校验、翻页上限截断显式暴露、空流不无限循环
  6. 接线 dispatch_engine._cloud_receipt：云端回执判据走统一入口（读全才判）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comment_stream import (  # noqa: E402
    READER, NaiveTransport, Transport, read_comments, comment_meta, has_receipt,
)

# ---------- 夹具：模拟 CNB 评论接口的默认 page_size=10 ----------
API_DEFAULT_PAGE_SIZE = 10
TOTAL = 89          # PR #161 实况量级（> 默认页大小，截断即显现）
RECEIPT_INDEX = 84  # 回执在尾部——裸调只读前 10 条必然漏掉


def make_comments(n=TOTAL):
    out = []
    for i in range(n):
        body = "[接单] 架构·开发 已接单" if i == RECEIPT_INDEX else "过程评论 #%d" % i
        out.append({"id": str(i), "author": "CodeBuddy", "body": body,
                    "created_at": "2026-10-18T%02d:00:00Z" % (i % 24)})
    return out


class FakeAPI(object):
    """按真实接口语义服务的假 API：默认 page_size=10，显式传参才给全量。"""

    def __init__(self, comments):
        self.comments = comments
        self.calls = []

    def request(self, page=None, page_size=None):
        size = page_size or API_DEFAULT_PAGE_SIZE
        page = page or 1
        self.calls.append({"page": page, "page_size": page_size, "routed_by": READER})
        start = (page - 1) * size
        return {
            "data": self.comments[start:start + size],
            "totalPages": max(1, -(-len(self.comments) // size)),
            "page": page, "pageSize": size,
        }


class FakePagedTransport(Transport):
    """统一入口的传输层：显式带 page_size，走假 API。"""

    def __init__(self, api):
        self.api = api

    def fetch(self, page, page_size):
        body = self.api.request(page, page_size)
        total_pages = body["totalPages"]
        return {"items": body["data"], "has_more": page < total_pages}


class FakeNaiveTransport(NaiveTransport):
    """裸调：不给 page/page_size，命中接口默认值（=静默截断）。"""

    def __init__(self, api):
        self.api = api

    def fetch(self, page, page_size):
        body = self.api.request()
        return {"items": body["data"], "has_more": False}


def naive_read_comments(api):
    """绕过统一入口的裸调写法（错误示范，用于防退化断言）。"""
    return FakeNaiveTransport(api).fetch(1, 0)["items"]


def run():
    api = FakeAPI(make_comments())

    # ---------- 1. 默认全量 ----------
    r = read_comments(kind="pulls", number=161, transport=FakePagedTransport(api))
    assert r["count"] == TOTAL, r["count"]
    assert len(r["comments"]) == TOTAL
    assert r["source"] == READER
    assert r["page_size"] > API_DEFAULT_PAGE_SIZE, r["page_size"]
    assert any(RECEIPT_INDEX == i for i, c in enumerate(r["comments"])
               if "[接单]" in c["body"]), "尾部回执没读到"
    # 显式分页参数真的发出去了（不依赖接口默认）
    assert all(c["page_size"] for c in api.calls[1:]), api.calls
    print("  ✅ 1. 默认全量：%d 条一次读全（page_size=%d）" % (r["count"], r["page_size"]))

    # ---------- 2. 防退化断言：裸调同一夹具读不全 → RED ----------
    naive = naive_read_comments(FakeAPI(make_comments()))
    assert len(naive) == API_DEFAULT_PAGE_SIZE, len(naive)
    assert len(naive) < TOTAL
    naive_receipt = has_receipt(naive, role="架构·开发")
    assert naive_receipt["received"] is False, "裸调本应漏掉尾部回执（假阴性）"
    assert naive_receipt["complete"] is None  # 裸调连"读全没有"都不知道
    # 统一入口在同一夹具上必须推翻裸调结论
    assert has_receipt(r, role="架构·开发")["received"] is True
    print("  ✅ 2. 防退化断言：裸调只读到 %d 条 → 假阴性（RED），入口读到全量纠正"
          % len(naive))

    # ---------- 3. 元信息可核验 ----------
    meta = comment_meta(r)
    assert meta["count"] == TOTAL and meta["complete"] is True
    assert meta["has_more"] is False and meta["truncated"] is False
    assert meta["pages"] == -(-TOTAL // r["page_size"])
    assert meta["source"] == READER
    print("  ✅ 3. 元信息：count=%d pages=%d has_more=%s complete=%s" % (
        meta["count"], meta["pages"], meta["has_more"], meta["complete"]))

    # ---------- 4. has_receipt 读取侧消费 ----------
    ok = has_receipt(r, role="架构·开发")
    assert ok["received"] and ok["degraded"] is False and ok["suspects"] == 1
    assert has_receipt(r, role="架构·不存在")["received"] is False
    # 读不全时不许谎报"未回执"：显式 degraded
    partial = dict(r, comments=r["comments"][:10], complete=False)
    d = has_receipt(partial, role="架构·开发")
    assert d["received"] is False and d["degraded"] is True
    print("  ✅ 4. has_receipt：读全判 received / 读不全显式 degraded（不谎报）")

    # ---------- 5. 参数与异常 ----------
    try:
        read_comments(kind="wiki", number=1, transport=FakePagedTransport(api))
        raise AssertionError("kind 校验失效")
    except ValueError:
        pass

    class EndlessTransport(Transport):
        def fetch(self, page, page_size):
            return {"items": [{"body": "x"}], "has_more": True}

    t = read_comments(kind="issues", number=1, transport=EndlessTransport(), max_pages=3)
    assert t["truncated"] is True and t["complete"] is False
    assert len(t["comments"]) == 3, "翻页硬上限未生效（会挂死）"

    class EmptyTransport(Transport):
        def fetch(self, page, page_size):
            return {"items": [], "has_more": True}

    e = read_comments(kind="issues", number=1, transport=EmptyTransport())
    assert e["count"] == 0 and e["complete"] is True and e["pages"] == 1
    print("  ✅ 5. 参数校验 / 翻页上限截断显式暴露 / 空流不无限循环")

    # ---------- 6. 接线 dispatch_engine._cloud_receipt（云端回执读取侧） ----------
    import tempfile
    os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix="_cs.db"))
    from data import admin
    admin.init()
    import comment_stream as cs
    import dispatch_engine

    orig = cs.read_comments
    try:
        # 同一夹具：回执在尾部 → 入口读全 → 判 received
        cs.read_comments = lambda **kw: orig(transport=FakePagedTransport(
            FakeAPI(make_comments())), kind="pull", number=161)
        ok = dispatch_engine._cloud_receipt([{"issue": "161", "role": "架构·开发",
                                              "kind": "pull"}])
        assert ok["verified_all_awake"] is True and ok["awake_count"] == 1, ok
        assert ok["detail"][0]["count"] == TOTAL and ok["detail"][0]["complete"] is True
        assert ok["detail"][0]["source"] == READER

        # 无回执 → 暴露 awaiting，不假装唤醒
        cs.read_comments = lambda **kw: orig(transport=FakePagedTransport(
            FakeAPI(make_comments())), kind="issues", number=166)
        bad = dispatch_engine._cloud_receipt([{"issue": "166", "role": "架构·不存在"}])
        assert bad["verified_all_awake"] is False
        assert bad["awaiting_receipt_count"] == 1

        # 读取失败 → 显式 degraded，绝不静默判"未回执"
        def boom(**kw):
            raise RuntimeError("network down")
        cs.read_comments = boom
        d = dispatch_engine._cloud_receipt([{"issue": "1", "role": "架构·开发"}])
        assert d["degraded"] and d["verified_all_awake"] is False
    finally:
        cs.read_comments = orig
    print("  ✅ 6. dispatch_engine._cloud_receipt 接线：读全判回执 / 读取失败显式 degraded")

    print("\n全部 6 组信号灯绿 ✅")
    return 0


if __name__ == "__main__":
    print("===== [comment_stream] Issue #166 统一读评论流入口 =====")
    raise SystemExit(run())
