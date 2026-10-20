# -*- coding: utf-8 -*-
"""评论流读取核心：默认全量 + 翻页取尽 + 可核验元信息（Issue #166）。"""
import json
import os
import urllib.error
import urllib.request

#: 统一入口标识——绕过它直接裸调 API 的调用方都会漏掉分页（防退化断言据此判 RED）
READER = "comment_stream.read_comments"
#: 默认文档页大小（CNB 接口实测默认 10，这里显式抬到接口上限量级）
DEFAULT_PAGE_SIZE = 100
#: 翻页硬上限（防御对端 has_more/分页异常的无限翻页）
MAX_PAGES = 200
#: 读取的最大尝试次数（网络重试）
MAX_RETRIES = 3

API_BASE = os.environ.get("CNB_API_BASE", "https://api.cnb.cool")
_KINDS = {"issue": "issues", "issues": "issues", "pull": "pulls", "pulls": "pulls"}

# ============================================================
# 传输层（transport）——把"怎么取一页"与"翻页取尽"解耦，便于离线夹具测试
# ============================================================
class Transport(object):
    """一页评论的取数契约：fetch(page, page_size) -> {"items": [...], "has_more": bool}"""

    def fetch(self, page, page_size):  # pragma: no cover - 接口定义
        raise NotImplementedError


class PagedTransport(Transport):
    """**合规**传输：显式带 `page` + `page_size`（统一入口内部使用）。"""

    def __init__(self, base_url, repo, kind, number, token=None, timeout=20,
                 opener=None):
        self.url = "%s/%s/-/%s/%s/comments" % (base_url, repo, _KINDS[kind], number)
        self.token = token
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def _get(self, url):
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Authorization": "Bearer %s" % self.token,
        })
        with self._opener(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch(self, page, page_size):
        body = self._get("%s?page=%d&page_size=%d" % (self.url, page, page_size))
        items = body.get("data") if isinstance(body, dict) else body
        if not isinstance(items, list):
            items = []
        has_more = body.get("has_more") if isinstance(body, dict) else None
        if has_more is None:
            total_pages = body.get("totalPages") if isinstance(body, dict) else None
            has_more = (page < int(total_pages)) if total_pages else (len(items) >= page_size)
        return {"items": items, "has_more": bool(has_more)}


class HttpTransport(PagedTransport):
    """真实 HTTP 传输（默认入口使用，从环境变量取 token）。"""

    def __init__(self, base_url, repo, kind, number, token=None, **kw):
        token = token or os.environ.get("cnbcooldong") or os.environ.get("CNB_TOKEN")
        if not token:
            raise RuntimeError("缺少 cnbcooldong/CNB_TOKEN 环境变量（CNB 访问令牌）")
        super(HttpTransport, self).__init__(base_url, repo, kind, number, token=token, **kw)


class NaiveTransport(Transport):
    """**裸调**传输：不带任何分页参数——接口默认 page_size=10 静默截断。

    存在的唯一目的：给防退化断言一个"错误示范"的对照实现，把坑锁死在测试里。
    生产读评论流**禁止**使用。
    """

    def __init__(self, base_url, repo, kind, number, token=None, **kw):
        self.url = "%s/%s/-/%s/%s/comments" % (base_url, repo, _KINDS[kind], number)

    def fetch(self, page, page_size):
        raise RuntimeError(
            "NaiveTransport 不支持分页裸调：不带 page/page_size 会静默截断"
            "（默认 page_size=10），请用 read_comments() 统一入口")


# ============================================================
# 统一入口
# ============================================================
def read_comments(kind="issues", number=None, repo=None, *, transport=None,
                  page_size=DEFAULT_PAGE_SIZE, max_pages=MAX_PAGES,
                  base_url=None, token=None, timeout=20, retries=MAX_RETRIES):
    """读评论流——**默认取全量**（显式分页 + 翻页至取尽），返回可核验元信息。

    Args:
        kind: "issue"/"issues"/"pull"/"pulls"
        number: Issue/PR 编号
        repo: "org/repo"（缺省取 CNB_REPO / CNB_REPO_SLUG 环境变量）
        transport: 注入传输层（离线夹具测试用）；缺省走 HttpTransport
        page_size: 每页条数（默认 100，显式传参，绝不依赖接口默认值）

    Returns:
        dict: comments(按时间正序) / count / pages / page_size / has_more /
              complete / truncated / source
    """
    if kind not in _KINDS:
        raise ValueError("kind 只支持 issue(s)/pull(s)，收到 %r" % (kind,))
    if not number:
        raise ValueError("number 必填（Issue/PR 编号）")
    if page_size <= 0:
        raise ValueError("page_size 必须 > 0")

    repo = repo or os.environ.get("CNB_REPO") or os.environ.get("CNB_REPO_SLUG") or ""
    if transport is None:
        if not repo:
            raise ValueError("repo 必填（org/repo），或设置 CNB_REPO 环境变量")
        transport = HttpTransport(base_url or API_BASE, repo, kind, number,
                                  token=token, timeout=timeout)

    items, page, has_more = [], 1, True
    while has_more and page <= max_pages:
        batch = _fetch_with_retry(transport, page, page_size, retries)
        got = batch.get("items") or []
        items.extend(got)
        has_more = bool(batch.get("has_more")) and bool(got)
        if not got:
            has_more = False
        page += 1
    pages = page - 1

    return {
        "kind": _KINDS[kind],
        "number": number,
        "comments": items,
        "count": len(items),
        "pages": pages,
        "page_size": page_size,
        "has_more": has_more,
        # complete：确定读全了（未触末页且未撞翻页上限）
        "complete": (not has_more) and pages < max_pages,
        "truncated": has_more or pages >= max_pages,
        "source": READER,
    }


def _fetch_with_retry(transport, page, page_size, retries):
    last = None
    for _ in range(max(1, retries)):
        try:
            return transport.fetch(page, page_size)
        except (urllib.error.URLError, OSError, ValueError) as e:  # noqa: PERF203
            last = e
    raise RuntimeError("读取评论流失败（page=%d）：%s" % (page, last))


def comment_meta(result):
    """供派发/校验判据消费的紧凑元信息（人可读 + 机器可判断"读全没有"）。"""
    return {
        "count": result.get("count", 0),
        "pages": result.get("pages", 0),
        "page_size": result.get("page_size"),
        "has_more": result.get("has_more"),
        "complete": result.get("complete"),
        "truncated": result.get("truncated"),
        "source": result.get("source"),
    }


def _texts(comments):
    for c in comments or []:
        if isinstance(c, dict):
            yield c.get("body") or c.get("content") or ""


def has_receipt(result, role=None, marker="[接单]"):
    """在**读全的**评论流里判定是否有接单回执（读取侧消费方，替代裸调）。

    Args:
        result: read_comments() 的返回体；也可直接传评论 list
        role: 可选，回执须提及的角色（如 "架构·开发"）
    Returns:
        dict: received(是否命中) / count(读到的评论总数) / complete(是否读全)
              / suspects(疑似回执条数，用于 truncated 时的显式暴露)
    """
    if isinstance(result, dict):
        comments, complete = result.get("comments") or [], result.get("complete")
    else:
        comments, complete = result or [], None
    hits = 0
    for body in _texts(comments):
        if marker in body and (role is None or role in body):
            hits += 1
    return {
        "received": hits > 0,
        "count": len(comments),
        "complete": complete,
        # 读不全时不谎报"未回执"：显式暴露可能假阴性
        "suspects": hits,
        "degraded": bool(complete is False and hits == 0),
    }
