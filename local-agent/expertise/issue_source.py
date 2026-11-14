# -*- coding: utf-8 -*-
"""
Issue 存量读取（issue_source · 建 Issue 闸门的唯一事实源）
=========================================================
为什么单独一层：闸门的幂等**全部依赖「存量读得到」**。第一版把读法各自写了两份
（`dispatch_engine._existing_issues` / `entries.cnb_live._gate_title`），并且都用
`--state all` —— 而 `cnb issues list-issues` 只认 `open`/`closed`，传 `all` 实测
返回 `status: 400` + rc=3。没人查 rc，错误文本被当 Issue 清单解析 → 存量恒为 `[]`
→ `reuse` 分支一次都进不去 → 闸门看着接上了，真实环境一条都没堵住。

本模块把"读存量"收成一个**唯一实现**，三处建 Issue 的出口都从这里取：
  - 全量语义 = **分别拉 `open` + `closed` 再合并**（两趟，缺一不可）；
    `--state all` 是非法值（实测 400），**不带 `--state` 实测只返回 open（total=12）**，
    另有 218 条已关闭的看不见 —— 所以「不带 --state 就是全量」这条路同样是错的；
  - **逐页翻到底**（`totalPages`）+ **严判 rc / errcode**，失败绝不冒充"仓库里没有 Issue"；
  - **失败不写缓存**（一次 400 不许污染整个进程），成功才缓存；
  - **新建回填**（`remember`）：同一进程里连建 N 条时，第 2 条起能看到第 1 条刚建的，
    同批内去重才成立 —— 否则"建之前"的快照永远看不到同批新建。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

PAGE_SIZE = 100
MAX_PAGES = 20

# 成功读到的存量（repo → items）；失败**不写**
_FETCH_CACHE = {}
# 本进程内已建的 Issue（repo → items）；与存量合并后参与幂等判定
_CREATED = {}


# ---------------------------------------------------------------------------
# 一、cnb CLI 调用（跨平台，不带 shell）
# ---------------------------------------------------------------------------
def _cnb_argv(args):
    """构造调用 cnb CLI 的 argv（跨平台）。

    Windows 上 `cnb` 常是 `cnb.ps1`/`cnb.cmd` 包装脚本，不能直接当可执行文件启动
    （实测 FileNotFoundError）——故按后缀分派；类 Unix 直接执行。
    """
    exe = shutil.which("cnb")
    if exe:
        lower = exe.lower()
        if lower.endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", exe] + list(args)
        if lower.endswith(".ps1"):
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", exe] + list(args)
        return [exe] + list(args)
    if os.name == "nt":
        return ["cmd.exe", "/c", "cnb"] + list(args)
    return ["cnb"] + list(args)


def _run(argv, timeout=180):
    """执行命令 → (rc, stdout, stderr)；不抛异常（由调用方判 rc）。"""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              errors="replace")
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "cnb CLI 不可用：未找到 cnb 可执行入口（检查 PATH / cnb --version）"
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时（>%ss）：%s" % (timeout, " ".join(list(argv)[:4]))


# ---------------------------------------------------------------------------
# 二、解析（cnb CLI 输出是 yaml 风格 `- number:` 块，不是 JSON）
# ---------------------------------------------------------------------------
def parse_issue_list(text):
    """从 yaml 风格输出提取 [{number,title,state,comment_count}]（缺字段不崩）。"""
    items, cur = [], None
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped.startswith("- number:"):
            if cur:
                items.append(cur)
            cur = {"number": stripped.split(":", 1)[1].strip().strip('"')}
            continue
        if cur is None:
            continue
        for key in ("title", "state", "comment_count"):
            if stripped.startswith(key + ":"):
                cur[key] = stripped.split(":", 1)[1].strip().strip('"')
                break
    if cur:
        items.append(cur)
    for item in items:
        try:
            item["comment_count"] = int(item.get("comment_count") or 0)
        except (TypeError, ValueError):
            item["comment_count"] = 0
    return [i for i in items if i.get("number")]


def _looks_like_error(text):
    """响应体是不是错误（cnb 有时 rc=0 但 body 是 errcode）。"""
    return bool(re.search(r"errcode:\s*[45]\d\d", text or ""))


# ---------------------------------------------------------------------------
# 三、读存量（唯一实现）
# ---------------------------------------------------------------------------
def _fetch_state(repo, state, *, page_size, max_pages, run):
    """拉单个状态的分页清单。返回 {ok, items, error, pages}。"""
    items = []
    pages = 0
    for page in range(1, max_pages + 1):
        argv = _cnb_argv(["issues", "list-issues", "--repo", repo,
                          "--page", str(page), "--page-size", str(page_size)])
        if state in ("open", "closed"):
            argv += ["--state", state]
        rc, out, err = run(argv)
        pages = page
        if rc != 0:
            return {"ok": False, "items": [], "pages": pages,
                    "error": "拉取 Issue 失败（%s page %s, rc=%s）：%s"
                             % (state or "open", page, rc, (err or out).strip()[:300])}
        if _looks_like_error(out):
            return {"ok": False, "items": [], "pages": pages,
                    "error": "拉取 Issue 失败（%s page %s，响应体报错）：%s"
                             % (state or "open", page, (out or "").strip()[:300])}
        batch = parse_issue_list(out)
        items.extend(batch)
        total_pages = None
        m = re.search(r"totalPages:\s*(\d+)", out or "")
        if m:
            total_pages = int(m.group(1))
        if total_pages is not None:
            if page >= total_pages:
                break
        elif len(batch) < page_size:
            break
    return {"ok": True, "items": items, "error": "", "pages": pages}


def fetch_issues(repo, *, page_size=PAGE_SIZE, max_pages=MAX_PAGES, state=None, runner=None):
    """拉取 Issue 清单。返回 {ok, items, error, pages}。

    state=None 是**全量语义**：分别拉 open 与 closed 再合并。
    为什么不"不带 `--state`"就算全量——实测（2026-11-14）不带 `--state` 只返回 open
    （total=12），closed 另有 218 条；而 `--state all` 是非法值（400）。所以全量必须
    两趟拉，否则已关闭的存量在幂等判定里根本看不见。

    任一分页失败即整体失败（ok=False + error），**绝不把错误文本当清单解析**。
    """
    run = runner or _run
    states = ("open", "closed") if state not in ("open", "closed") else (state,)
    merged, seen, pages, errors = [], set(), 0, []
    for st in states:
        snap = _fetch_state(repo, st, page_size=page_size, max_pages=max_pages, run=run)
        pages += snap["pages"]
        if not snap["ok"]:
            errors.append(snap["error"])
            continue
        for item in snap["items"]:
            num = str(item.get("number") or "")
            if not num or num in seen:
                continue
            seen.add(num)
            merged.append(item)
    if errors:
        return {"ok": False, "items": [], "pages": pages, "error": "；".join(errors)}
    return {"ok": True, "items": merged, "error": "", "pages": pages}


def _merge(repo, items):
    """存量 + 本进程已建 合并（按 number 去重，已建优先保留）。"""
    merged, seen = [], set()
    for item in list(_CREATED.get(repo, [])) + list(items or []):
        num = str(item.get("number") or "")
        if not num or num in seen:
            continue
        seen.add(num)
        merged.append(item)
    return merged


def existing(repo, *, refresh=False, runner=None):
    """给闸门用的存量视图。返回 {ok, items, error, cached}。

    **只有成功读到非空清单才缓存**：一次 400/超时得到空，不许被永久记住，
    否则同进程后续派发的幂等再也恢复不了（第一版正是这么坏的）。
    """
    if not repo:
        return {"ok": False, "items": [], "error": "未给 repo，无法读存量", "cached": False}
    if not refresh and repo in _FETCH_CACHE:
        return {"ok": True, "items": _merge(repo, _FETCH_CACHE[repo]), "error": "",
                "cached": True}
    snap = fetch_issues(repo, runner=runner)
    if snap["ok"] and snap["items"]:
        _FETCH_CACHE[repo] = list(snap["items"])
    return {"ok": snap["ok"], "items": _merge(repo, snap["items"]),
            "error": snap["error"], "cached": False}


def remember(repo, number, title, state="open"):
    """新建 Issue 成功后回填 —— 同批内第 2 条起也能看到第 1 条（同批去重的前提）。"""
    if not repo or number in (None, ""):
        return False
    entry = {"number": str(number), "title": title or "", "state": state}
    bucket = _CREATED.setdefault(repo, [])
    for i, old in enumerate(bucket):
        if old.get("number") == entry["number"]:
            bucket[i] = entry
            return True
    bucket.append(entry)
    return True


def reset_cache(repo=None):
    """清缓存（测试/演练用）：不给 repo 就全清。"""
    if repo is None:
        _FETCH_CACHE.clear()
        _CREATED.clear()
        return True
    _FETCH_CACHE.pop(repo, None)
    _CREATED.pop(repo, None)
    return True


__all__ = ["fetch_issues", "existing", "remember", "reset_cache", "parse_issue_list"]
