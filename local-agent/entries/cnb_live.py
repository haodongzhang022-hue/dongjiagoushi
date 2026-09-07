# -*- coding: utf-8 -*-
"""
真实 cnb.cool 传输通道（entries.cnb_live · Issue #105 真实本地实测 · module platform-adapter v0.5.0）
================================================================================================
用户（#105 评论）明确：「使用模拟数据的我们一般认为是不可信的，所以你开发完成这一部分
之后，下一步就要尝试去用本地实测了。发送信号尝试做配合，看看能不能达成好的效果，不行的话，
然后去做适配。」

v0.3.0 bridge / v0.4.0 dashboard 默认走**本地模拟传输（mock transport）**，供确定性单测。
但 mock 只能证明「协议/状态机对」，不能证明「真实跨端配合能达成好效果」——用户点名其不可信。

本模块 v0.5.0 落地**真实 cnb.cool 传输通道（live transport）**：用真实 `cnb` CLI 把
bridge 的「云开发请求 → 云端异步开发 → 产出回传」从『模拟』提升为『真实信号配合』：
  - 发真实信号：request 时真实在目标仓库**创建云开发请求 Issue** 作 cloud_ref 锚（发一次真实信号）；
  - 查真实产出：poll 时真实读云端 Issue / PR / CI 状态（merged/done/need_fix 对照规范打标）；
  - 真实回执：collect 完成后给真实 Issue 发一条真实**结果回执评论**（留痕、闭环）。

真实通道探测（probe）即用户要的「发送信号尝试做配合，看能不能达成好的效果」——通道可用
则达成，通道被限则如实降级并暴露，不假装成功。

与 mock 的取舍（用户诉求优先）：
  - **默认真实**：本环境有 `cnb` CLI / git remote → `default_transport()` 返回 live（真实），
    不再默认 mock。mock 仅保留为**无 cnb CLI 的单测/本地兜底**，且显式标注 mock（不骗人）。
  - 单测仍走 mock（确定性）；真实配合走 live（可核验）。

能力暴露：
  - `live_transport()`      返回可注入 bridge request/collect 的 transport 字典
  - `default_transport()`   检测 cnb CLI 可用 → live；不可用 → mock（兜底/单测）
  - `send(handle)`          真实发信号：创建云开发请求 Issue 作 cloud_ref 锚
  - `poll(handle)`          真实读云端产出（Issue/PR/CI 状态）
  - `ack(handle)`           真实回执：collect 后给云端 Issue 发结果评论
  - `probe()`               通道探测（用户要的"发送信号尝试配合"落点）
  - `cli_live()`            run.py --live 语义入口
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 默认目标仓库（本体系仓库）；可用 git remote / 环境变量探测覆盖
_DEFAULT_REPO = "dongdongxiaozu/dongjiagoushi"


# ---------------------------------------------------------------------------
# 一、cnb CLI 可用性 + 默认仓库探测（不写死，能探测就探测）
# ---------------------------------------------------------------------------
def _cnb_available():
    """探测真实 cnb CLI 是否可用（决定默认真实 or mock 兜底）。"""
    return shutil.which("cnb") is not None


def _detect_repo():
    """从 git remote / 环境变量探测默认目标仓库；探测不到用内置默认。"""
    repo = os.environ.get("CNB_REPO_SLUG")
    if repo:
        return repo
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        # https://cnb.cool/<org>/<repo>.git  →  org/repo
        if "cnb.cool" in out and ".git" in out:
            core = out.split("cnb.cool/")[-1].replace(".git", "").strip("/")
            if "/" in core:
                return core
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_REPO


def _run_cnb(args, timeout=60):
    """执行一条真实 cnb 命令，返回解析后的 JSON dict（非 None 即真实成功）。

    args：cnb 子命令参数列表（不含 cnb 前缀）。
    失败返回 {'ok': False, 'error': ...}，不抛异常——让上游如实处置/降级。
    """
    cmd = ["cnb"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"cnb 执行失败: {e}"}
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip() or r.stdout.strip() or "cnb 非零返回"}
    text = (r.stdout or "").strip()
    if not text:
        return {"ok": True, "data": {}}
    # cnb 输出是 YAML 风格（status/data 缩进），先尝试 JSON；失败则原样返回
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {"ok": True, "raw": text}


# ---------------------------------------------------------------------------
# 二、真实信号发送（request：在云端真实建云开发请求 Issue 作锚）
# ---------------------------------------------------------------------------
def send(handle, repo=None, create_issue=True):
    """真实发信号：把云开发请求在目标仓库落地成一个真实 Issue，作为 cloud_ref 锚。

    返回：{ ok, cloud_ref: {issue_id, url, sent_via}, status }
    """
    repo = repo or _detect_repo()
    req = handle.get("req") or "云开发请求"
    title = (req.strip().splitlines()[0])[:60] or "云开发请求"
    # 若已有关联 issue_id 则复用（在既有 Issue 上发真实信号评论），否则真实新建
    existing = handle.get("issue_id")
    if existing:
        # 复用：在既有 Issue 上发一条"云开发请求已投递"真实评论作为信号
        body = ("[bridge 真实传输] 云开发请求已投递（entries.cnb_live · v0.5.0 真实本地实测）：\n"
                f"```\n{req}\n```")
        res = _run_cnb(["issues", "post-issue-comment",
                        "--repo", repo, "--number", str(existing), "--body", body])
        issue_id = str(existing)
        ok = res.get("ok", False)
    else:
        body = (f"# 云开发请求（bridge 真实传输 · {datetime.utcnow().isoformat()}）\n\n"
                f"```\n{req}\n```\n\n"
                "> 本条由 `entries.cnb_live` 真实传输通道自动创建，作 bridge 云开发请求的"
                "cloud_ref 锚点；开发完成回传结果后此 Issue 承载闭环留痕。")
        res = _run_cnb(["issues", "create-issue",
                        "--repo", repo, "--title", title, "--body", body])
        ok = res.get("ok", False)
        issue_id = None
        if ok:
            # cnb 输出为 YAML（data: 缩进），尽力解析 number
            issue_id = _extract_issue_id(res, text=res.get("raw", ""))
    if not ok:
        return {"ok": False,
                "error": res.get("error") or res.get("raw") or "cnb 建 Issue 失败",
                "cloud_ref": {"issue_id": issue_id or "", "sent_via": handle.get("entry")},
                "status": "pending"}
    return {
        "ok": True,
        "cloud_ref": {
            "issue_id": issue_id or "",
            "repo": repo,
            "url": f"https://cnb.cool/{repo}/-/issues/{issue_id}" if issue_id else "",
            "sent_via": handle.get("entry") or "cnb",
            "transport": "live-cnb",
            "created_at": datetime.utcnow().isoformat(),
        },
        "status": "in_cloud_dev",
    }


def _extract_issue_id(res, text=""):
    """从 cnb create-issue 输出中解析出 issue number（YAML 风格 data.number）。

    若 res 已是 dict 且含 data.number 直接取；否则从 raw 文本正则抽取。
    """
    try:
        if isinstance(res, dict):
            d = res.get("data")
            if isinstance(d, dict) and d.get("number"):
                return str(d["number"])
    except Exception:  # noqa: BLE001
        pass
    import re
    m = re.search(r"number:\s*[\"']?(\d+)", text or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# 三、真实产出收集（poll：读云端真实 Issue / PR / CI 状态）
# ---------------------------------------------------------------------------
def poll(handle, repo=None):
    """真实读云端产出信号（对照云端 Issue 真实状态判定，不臆造 PR 关联）。

    真实读云端 Issue #number 的 state 与 comment_count：
      - Issue closed          → 云端已收尾（done）
      - Issue open 且无进展评论 → 云端仍在处理（in_cloud_dev 信号：in_progress）
      - Issue open 且有回执/评论 → 云端已产出待收（done，developer 在 cloud_result
                                   显式填 pr_ids 做真实关联，poll 不臆造 PR 列表）

    返回：{ ok, state, issue_state, comment_count, pr_ids, note }
      state：in_progress（云端处理中） / done（云端已产出/收尾待收集）
      pr_ids：真实 PR 关联由 collect 时显式传入（开发者完成填），poll 不扫全仓库 PR。
    """
    repo = repo or _detect_repo()
    cloud_ref = handle.get("cloud_ref") or {}
    issue_id = cloud_ref.get("issue_id") or handle.get("issue_id")
    if not issue_id:
        return {"ok": False, "state": "unknown",
                "note": "无 cloud_ref.issue_id 锚，无法真实 poll", "pr_ids": []}
    g = _run_cnb(["issues", "get-issue", "--repo", repo, "--number", str(issue_id)])
    if not g.get("ok"):
        return {"ok": False, "state": "unknown",
                "note": g.get("error") or "读云端 Issue 失败", "pr_ids": []}
    raw = g.get("raw") or ""
    issue_state = "open"
    comment_count = 0
    # 从 cnb get-issue YAML 输出解析真实 state / comment_count
    import re
    m_state = re.search(r"state:\s*([a-z_]+)", raw)
    if m_state:
        issue_state = m_state.group(1)
    m_cc = re.search(r"comment_count:\s*(\d+)", raw)
    if m_cc:
        comment_count = int(m_cc.group(1))
    # 云端真实状态 → bridge 语义 state
    if issue_state == "closed":
        state = "done"                     # Issue 已关闭 = 云端收尾
    elif comment_count and comment_count >= 2:
        state = "done"                     # 有回执/产出评论 = 云端已产出待收集
    else:
        state = "in_progress"              # open 无回执 = 云端仍在异步开发
    return {"ok": True, "state": state, "issue_state": issue_state,
            "comment_count": comment_count, "pr_ids": [],
            "note": f"真实 poll：Issue #{issue_id} @ {repo} (state={issue_state},"
                    f" comment={comment_count})"}


def ack(handle, repo=None):
    """真实回执：collect 完成后给云端 Issue 发一条结果回执评论（留痕、闭环）。"""
    repo = repo or _detect_repo()
    cloud_ref = handle.get("cloud_ref") or {}
    issue_id = cloud_ref.get("issue_id") or handle.get("issue_id")
    cr = handle.get("cloud_result") or {}
    if not issue_id:
        return {"ok": False, "error": "无 issue_id 无法回执"}
    body = ("[bridge 真实传输·结果回执] 云开发产出已收集并对齐本地：\n"
            f"- state: {cr.get('state', '')}\n"
            f"- pr_ids: {','.join(cr.get('pr_ids') or []) or '—'}\n"
            "- 已回写本地 relay/data（align_local），闭环完成。")
    res = _run_cnb(["issues", "post-issue-comment",
                    "--repo", repo, "--number", str(issue_id), "--body", body])
    return {"ok": res.get("ok", False),
            "error": res.get("error") if not res.get("ok") else None,
            "issue_id": issue_id}


# ---------------------------------------------------------------------------
# 四、通道探测（用户要的"发送信号尝试配合"落点）
# ---------------------------------------------------------------------------
def probe(repo=None, send_signal=False):
    """真实通道探测：验证 cnb.cool 真实传输能否配合。

    探测项：
      cnb_cli   真实 cnb 命令是否存在
      repo      目标仓库探测
      read      真实读云端（list-issues + list-pulls）是否通
      send      真实发信号（create-issue）——仅在 send_signal=True 时真实建（避免每次
                snapshot 都污染仓库）；False 默认只读探测即可证明通道可达。

    默认只读、轻量（供 dashboard health 高频调用不造 Issue）；需要真发一次信号做配合
    实证时显式 send_signal=True（CLI --live probe 也可 --probe-send）。通=达成配合；
    被限=如实降级暴露，不假装成功。
    """
    repo = repo or _detect_repo()
    out = {
        "module": "platform-adapter",
        "capability": "entries.cnb_live (真实 cnb.cool 传输通道 · v0.5.0)",
        "repo": repo,
        "cnb_cli": _cnb_available(),
        "checked_at": datetime.utcnow().isoformat(),
        "probe": {},
    }
    if not out["cnb_cli"]:
        out["health"] = {"status": "degraded", "light": "🔴",
                         "note": "无 cnb CLI → 走 mock 兜底（单测/无 cnb 环境）"}
        out["transport"] = "mock"
        return out
    # 真实读（list-issues + list-pulls open，轻量只读，证明通道可达）
    read = _run_cnb(["issues", "list-issues", "--repo", repo,
                     "--state", "open", "--page-size", "1"])
    read_pr = _run_cnb(["pulls", "list-pulls", "--repo", repo,
                        "--state", "all", "--page-size", "1"])
    out["probe"]["read"] = bool(read.get("ok") and read_pr.get("ok"))
    out["probe"]["read_note"] = "" if out["probe"]["read"] else (
        read.get("error") or read_pr.get("error") or "读失败")
    # 真实发信号（可选：仅 send_signal=True 时 create-issue，标题带 probe 标识）
    out["probe"]["send"] = False
    out["probe"]["send_issue_id"] = ""
    if send_signal:
        send_res = _run_cnb(["issues", "create-issue", "--repo", repo,
                             "--title", "probe: cnb_live 真实通道探测",
                             "--body", "entries.cnb_live 通道探测信号（probe）——"
                                       "验证真实传输可达成配合。该条为 send_signal 探测用。"
                                       "桥接实测后关闭，不承载业务。"])
        out["probe"]["send"] = bool(send_res.get("ok"))
        out["probe"]["send_issue_id"] = _extract_issue_id(
            send_res, send_res.get("raw", ""))
    ok = bool(out["probe"]["read"] and (out["probe"]["send"] or not send_signal))
    out["health"] = {"status": "ok" if ok else "degraded",
                     "light": "🟢" if ok else "🔴",
                     "note": ("真实通道可达成配合（read 通）" if ok
                              else "通道受限，如实降级暴露（不假装成功）")}
    out["transport"] = "live-cnb" if ok else "mock"
    return out


# ---------------------------------------------------------------------------
# 五、transport 组装（可注入 bridge request/collect）
# ---------------------------------------------------------------------------
def live_transport(repo=None):
    """真实传输通道：可作为 transport 参数注入 bridge.request_cloud_dev /
    collect_cloud_result。

    { name, send, poll, ack }
    """
    return {
        "name": "live-cnb",
        "send": lambda h: send(h, repo=repo),
        "poll": lambda h: poll(h, repo=repo),
        "ack": lambda h: ack(h, repo=repo),
    }


def mock_transport():
    """mock 传输（仅无 cnb CLI 兜底 / 单测用，显式标注不骗人）。"""
    def _ms(h):
        return {"ok": True,
                "cloud_ref": {"issue_id": h.get("issue_id") or "sim-issue",
                              "sent_via": h.get("entry"), "transport": "mock"},
                "status": "in_cloud_dev"}
    return {"name": "mock", "send": _ms, "poll": lambda h: {
        "ok": True, "state": "done", "pr_ids": [], "note": "mock poll"}, "ack": lambda h: {"ok": True}}


def default_transport(repo=None):
    """默认传输：有真实 cnb CLI → live（真实）；无 → mock（兜底/单测）。

    用户「模拟数据不可信」→ 只要环境能真实连 cnb.cool，就默认真实，不默认 mock。
    """
    if _cnb_available():
        return live_transport(repo)
    return mock_transport()


def cli_live(action="probe", repo=None, send_signal=False):
    """run.py --live 语义入口。

    action: probe / probe-send（真实发一次信号做配合实证） / transport
    """
    if action in ("probe", "probe-send"):
        return probe(repo, send_signal=(action == "probe-send"))
    if action == "transport":
        tr = default_transport(repo)
        return {"ok": True, "transport": tr["name"],
                "note": "live-cnb=真实通道（默认真实）; mock=仅单测/无cnb兜底"}
    return {"ok": False, "error": f"未知 --live action: {action}（支持 probe/transport）"}
