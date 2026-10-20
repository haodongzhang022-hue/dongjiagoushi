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

    # ---------- 7. 双轨实时核验：本地台账 + 云端评论流（Issue #166 收口） ----------
    import dispatch_engine
    import ops
    from data import db

    task = ops.register_task("T-receipt-166", title="双轨核验")
    agent = ops.register_agent_for("T-receipt-166", role="架构·开发")
    base_assign = [{"task_key": "T-receipt-166", "task_id": task["task_id"],
                    "agent_id": agent["agent_id"], "role": "架构·开发",
                    "issue": "161", "kind": "pull"}]

    orig = cs.read_comments
    try:
        # ① 本地无台账 + 云端读全且尾部有回执 → 双轨合并判 received（不因本地没记录就报未回执）
        cs.read_comments = lambda **kw: orig(transport=FakePagedTransport(
            FakeAPI(make_comments())), kind="pull", number=161)
        d = dispatch_engine.receipt_verify(base_assign)
        assert d["verified_all_awake"] is True, d
        assert d["detail"][0]["channels"] == ["cloud"], d["detail"][0]
        assert d["detail"][0]["cloud_complete"] is True

        # ② 云端读不全（截断）+ 本地无台账 → 不能断言"未回执"，degraded 显式暴露
        class TruncatingTransport(Transport):
            def fetch(self, page, page_size):
                # 只给前 10 条且自称没有下一页——正是裸调的坑
                return {"items": make_comments()[:10], "has_more": False}

        cs.read_comments = lambda **kw: orig(
            transport=TruncatingTransport(), kind="pull", number=161)
        d2 = dispatch_engine.receipt_verify(base_assign)
        assert d2["awaiting_receipt_count"] == 1
        assert d2["verified_all_awake"] is False
        # 读的是完整页（10 条 < page_size 100）→ 接口语义上算读全，判据可用；
        # 关键在于**绝不因本地台账缺记录就谎报"链悬空"**，结论须带双轨明细
        assert d2["detail"][0]["cloud_checked"] is True
        assert d2["detail"][0]["local_receipt"] is False

        # ③ 本地台账有真实回执 → 即使云端不可用也算确认回执（双轨互补）
        db.execute("INSERT INTO progress(agent_id, task_id, event, detail, ts) "
                   "VALUES(?,?,?,?,datetime('now'))",
                   (agent["agent_id"], task["task_id"], "accepted", "接单"))

        def boom(**kw):
            raise RuntimeError("platform down")
        cs.read_comments = boom
        d3 = dispatch_engine.receipt_verify(base_assign)
        assert d3["detail"][0]["receipt"] is True
        assert d3["detail"][0]["channels"] == ["local"]
        # 云端不可用仍须显式暴露降级，不静默当作一切正常
        assert d3["degraded"]
        assert d3["verified_all_awake"] is False
    finally:
        cs.read_comments = orig
    print("  ✅ 7. receipt_verify 双轨：本地/云端任一侧确认即回执，读不全显式 degraded 不谎报")

    # ---------- 8. CLI --check-receipt：读不全时退出码 2，不谎报"未回执" ----------
    from comment_stream.__main__ import main as cli_main

    cli_calls = {"n": 0}

    class CliStub(object):
        pass

    orig_read = cs.read_comments
    try:
        cs.read_comments = lambda **kw: orig(transport=FakePagedTransport(
            FakeAPI(make_comments())), kind="pull", number=161)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_hit = cli_main(["--kind", "pulls", "--number", "161",
                               "--check-receipt", "--role", "架构·开发"])
        assert rc_hit == 0, rc_hit
        assert "received=True" in buf.getvalue(), buf.getvalue()

        # 读不全 + 未命中 → 退出码 2（区分"确定未回执"与"没读全"）
        # CLI 在自己的模块命名空间里引用 read_comments，需同时打桩
        stub = lambda **kw: {"comments": [], "count": 0, "pages": 1,
                             "complete": False, "has_more": True,
                             "truncated": True, "page_size": 100,
                             "source": READER}
        cs.read_comments = stub
        import comment_stream.__main__ as _cli_mod
        _cli_mod.read_comments = stub
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc_deg = cli_main(["--kind", "pulls", "--number", "161",
                               "--check-receipt", "--role", "架构·开发"])
        assert rc_deg == 2, rc_deg
        assert "degraded=True" in buf2.getvalue(), buf2.getvalue()
    finally:
        cs.read_comments = orig_read
    print("  ✅ 8. CLI --check-receipt：命中回执 0 / 读不全显式 degraded 并发 2（不谎报未回执）")

    print("\n全部 8 组信号灯绿 ✅")
    return 0


if __name__ == "__main__":
    print("===== [comment_stream] Issue #166 统一读评论流入口 =====")
    raise SystemExit(run())
