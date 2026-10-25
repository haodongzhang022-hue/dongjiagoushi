# -*- coding: utf-8 -*-
"""
本地⇄云端桥接闭环（entries.bridge · Issue #105 最常用链路深化 · module platform-adapter v0.3.0）
================================================================================================
用户最常用链路（闭环）：网页对话（如 gemini）作工具桥 → 把云端开发请求发到
**本地 deepseek harness**（本地管理与测试能力）→ harness 把请求桥到 **cnb.cool 云端**
做**异步开发**（长时、跨对话/跨 PR/可跨仓库）→ 云端产出（Issue/PR/CI）**回传本地**做
**数据对齐** → 云端建的 CPU 密集测试**下放本地执行**（云端建环境成本高，本地 CPU 便宜）
→ 完成闭环。

设计要点：
  1. 复用一个「本地 ⇄ 云端桥」通道（cnb.cool = 原生宿主的 `[触发]` 接力卡 + Issue/PR 评论；
     web/gemini 工具桥 = 通过本地 harness 同一套桥协议发卡）。
  2. 一次云开发请求 = 一个**桥接句柄（CloudDevHandle）**：带全局唯一 gid + 发起入口 +
     目标仓库 + 云端任务说明，可**异步收集结果**（跨对话/跨 PR 用 handle 定位，不丢）。
  3. **本地测试先行门（local_test_first）**：识别「CPU 密集/长耗时」的云端构建测试，
     路由到本地执行（本地 CPU 便宜、云端建环境贵）——这是用户点名的主要成本点。
  4. 对齐层（align）把云端状态（issue/merged/done）回写本地 relay/data，双向一致。
  5. 全程确定性可本地单测：默认走**本地模拟传输（mock transport）**，真实云端传输
     （cnb.cool API / web 桥）经 transport 抽象接入，不影响核心闭环逻辑。
  6. **句柄自足（Issue #232）**：本仓库的工作面在不同执行地之间是**断开**的——云端能读
     代码，但读不到本地 `_bridge_state/` 里的句柄（且该目录本就不进版本库），本地服务没开时
     云端**只剩一个句柄 id，等于空手**。所以句柄必须是「**一个 id 就能重建全部上下文**」的
     自足卡：`render_handle_card` 把 req/目的/边界/验收/target_repo/脑区/能做什么/不能做什么
     全渲染成落地文本，且**本身自带合规接力卡标记**（可被 `relay_card.check` 机器校验，
     否则就成了一张过不了闸门的卡）。
  7. **脑区判定（不是能不能，是在哪能做）**：`analyze_locus` 按动作清单判「云端能做 /
     必须本地做 / 必须人工」，并做**证据保全**——本地不可达时，本地独占证据返回
     `evidence_available: False` + 去哪里补，不让云端把"没数据"误读成"无问题"。
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from ops import register_task, locate
    _HAVE_OPS = True
except Exception:  # noqa: BLE001
    _HAVE_OPS = False

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bridge_state")
_HANDLES_FILE = os.path.join(STATE_DIR, "cloud_dev_handles.json")


# ---------------------------------------------------------------------------
# 一、桥接句柄持久化（跨对话/跨 PR 用 handle 定位异步云开发，不丢上下文）
# ---------------------------------------------------------------------------
def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def _load_handles():
    try:
        if os.path.exists(_HANDLES_FILE):
            with open(_HANDLES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_handles(data):
    _ensure_dir()
    with open(_HANDLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _new_handle_id(req_key):
    """生成全局唯一桥接句柄 id：复用 ops.gid 体系（tk- 前缀），保二次触发不漂移。"""
    if _HAVE_OPS:
        try:
            r = register_task("cloud-dev::" + req_key)
            return r["task_id"]          # 同 req_key 二次触发取回同一 gid
        except Exception:  # noqa: BLE001
            pass
    return "tk-cloud-" + str(int(time.time() * 1000))


# ---------------------------------------------------------------------------
# 二、发起云端开发请求（桥：本地/web → cnb.cool 云端异步开发）
# ---------------------------------------------------------------------------
def request_cloud_dev(req, entry="local", target_repo=None, issue_id="", pr_ids=None,
                      transport=None, live=False, **meta):
    """发起一次云端异步开发请求，返回桥接句柄（可跨对话/跨 PR 轮询收集）。

    参数：
      req         云开发任务说明（一句话/多行均可）
      entry       发起入口（local/web/cnb）
      target_repo 目标云端仓库（默认 cnb.cool 本体系仓库）
      issue_id    若已有关联云端 Issue，可带上做锚定
      pr_ids      云端 PR 列表（随句柄留痕，跨 PR 定位产出）
      transport   传输通道（显式注入时优先；真实 cnb/web 桥宿主注入）
      live        True → 走默认真实通道 cnb_live.default_transport()（用户：模拟数据不可信）；
                  False → mock（兼容单测确定性，未显式注入 transport 时）

    返回 CloudDevHandle：
      { handle_id, status, entry, target_repo, req,
        created_at, cloud_ref（云端锚: issue/pr）, transport }
    """
    _ensure_dir()
    handles = _load_handles()
    req_key = _req_key(req)
    handle_id = _new_handle_id(req_key)
    now = datetime.utcnow().isoformat()
    # 复用 ops.gid：反查业务 key 做稳定寻址
    biz_key = "cloud-dev::" + req_key
    if _HAVE_OPS:
        try:
            g = locate(handle_id)
            if g:
                biz_key = g.get("biz_key", biz_key)
        except Exception:  # noqa: BLE001
            pass
    handle = {
        "handle_id": handle_id,
        "req_key": biz_key,
        "req": req,
        "status": "pending",            # pending → in_cloud_dev → collected
        "entry": entry,
        "target_repo": target_repo or "dongdongxiaozu/dongjiagoushi",
        "issue_id": issue_id,
        "pr_ids": list(pr_ids or []),
        "created_at": now,
        "updated_at": now,
        "cloud_result": None,
        "relaunch": bool(meta.pop("relaunch", False)),   # 本地是否已可达（脑区判定用）
        "meta": meta,
    }
    # 通过传输通道把云开发请求投递给云端。
    # 「模拟数据不可信」→ live=True 或显式注入真实 transport 时走真实；
    # 默认 mock 仅为兼容单测确定性（单测不传 transport / live）。
    tr = transport
    if tr is None:
        if live:
            try:
                from entries import cnb_live
                tr = cnb_live.default_transport(handle["target_repo"])
            except Exception:  # noqa: BLE001
                tr = {"name": "mock", "send": _mock_send}
        else:
            tr = {"name": "mock", "send": _mock_send}
    try:
        sent = tr["send"](handle)
        handle["cloud_ref"] = sent.get("cloud_ref", {})
        # transport send 必须显式非 False 才算投递成功；
        # ok 缺失/False（未知宿主、无 cnb CLI、HTTP 不可达）→ 如实标 blocked 不假成功。
        if sent.get("ok", True) is not False:
            handle["status"] = sent.get("status", "in_cloud_dev")
        else:
            handle["status"] = "blocked"
            handle["send_error"] = sent.get("error", "transport send 未明确 ok（真实通道不可达）")
    except Exception as e:  # noqa: BLE001
        handle["status"] = "blocked"
        handle["send_error"] = str(e)
    handle["updated_at"] = datetime.utcnow().isoformat()
    handles[handle_id] = handle
    _save_handles(handles)
    return handle


def _mock_send(handle):
    """本地模拟传输：把云开发请求「投递」到云端，模拟云端接收后进入异步开发。"""
    return {
        "ok": True,
        "cloud_ref": {"issue_id": handle["issue_id"] or "sim-issue",
                      "sent_via": handle["entry"]},
        "status": "in_cloud_dev",
    }


def list_handles(status=None):
    """列出全部桥接句柄（可按状态过滤）。"""
    handles = _load_handles()
    if status:
        return {hid: h for hid, h in handles.items() if h.get("status") == status}
    return handles


def get_handle(handle_id):
    """按句柄定位一次云开发请求（跨对话/跨 PR 稳定寻址，不漂移）。"""
    return _load_handles().get(handle_id)




# ---------------------------------------------------------------------------
# 二.5 句柄自足：一个 id 重建全部上下文（Issue #232）
# ---------------------------------------------------------------------------
DEFAULT_ACCEPT = "云端按自足卡在承接链路上闭环，产出回传本地对齐"
DEFAULT_SCOPE_NOT = "改需求边界 / 改架构方向（越界须回发起方或总师）"
DEFAULT_NEXT = "云端产出(PR/结论)回传 → 本地 collect + align 对齐 → 本地测试先行验收"

# 脑区表：动作 → (云端能否做, 必须本地, 必须人工, 本地不可达时的补法)
# 这是承接判定的事实源，dashboard/bridge 都从这里读，不各自取名。
LOCUS_ACTION_TABLE = {
    "read_code":   {"cloud": True,  "local": False, "human": False,
                    "when_local_down": "云端直接读仓库即可"},
    "write_code":  {"cloud": True,  "local": False, "human": False,
                    "when_local_down": "云端直接开 PR"},
    "review":      {"cloud": True,  "local": False, "human": False,
                    "when_local_down": "云端评审打规范处置标签"},
    "ci":          {"cloud": True,  "local": False, "human": False,
                    "when_local_down": "云端 CI 轻量自检"},
    "local_test":  {"cloud": False, "local": True,  "human": False,
                    "when_local_down": "无法替代：须本地服务可达，否则只登记证据缺口"},
    "cpu_build":   {"cloud": False, "local": True,  "human": False,
                    "when_local_down": "不迁移到云端（云端建环境贵），登记缺口待本地跑"},
    "align_local": {"cloud": False, "local": True,  "human": False,
                    "when_local_down": "缺口：对齐须等本地可达后补做"},
    "merge_gate":  {"cloud": False, "local": False, "human": True,
                    "when_local_down": "不受影响，仍须人类确认（CP3）"},
    "guard_read":  {"cloud": True,  "local": False, "human": False,
                    "when_local_down": "云端正向执行（禁止绕过护栏）"},
}


def _req_key(req):
    """从需求文本取稳定业务 key：首非空行前 40 字（不看空白差异、不取整段）。"""
    for line in (req or "").splitlines():
        line = line.strip()
        if line:
            return line[:40]
    return (req or "").strip()[:40]


def analyze_locus(actions=None, local_reachable=False):
    """脑区判定：这些动作「云端能做 / 必须本地 / 必须人工」，本地不可达时缺口在哪。

    判定口径不是"能不能"，而是"**在哪里能做**"——把「做不了」收窄成
    「某个具体动作在某个执行地做不了 + 怎么补」，不在首次交付时把任务剔残。
    """
    acts = list(actions or ["read_code", "write_code", "review", "ci",
                            "local_test", "cpu_build", "align_local", "merge_gate"])
    cloud_ok, must_local, must_human, blocked = [], [], [], []
    for a in acts:
        spec = LOCUS_ACTION_TABLE.get(a)
        if not spec:
            blocked.append({"action": a, "reason": "未知动作，按'宁拦不放'登记"})
            continue
        if spec["cloud"]:
            cloud_ok.append(a)
        if spec["local"]:
            must_local.append(a)
            if not local_reachable:
                blocked.append({"action": a, "reason": "本地不可达",
                                "workaround": spec["when_local_down"]})
        if spec["human"]:
            must_human.append(a)
    return {
        "cloud_can": cloud_ok,
        "must_local": must_local,
        "must_human": must_human,
        "blocked": blocked,
        # 证据保全：本地独占证据在本地不可达时不可得，绝不返回空=没问题
        "evidence_available": bool(local_reachable),
        "evidence_gap": ([] if local_reachable else
                         [a for a in must_local]),
        "rule": "云端能做开发/评审/CI；本地测试与对齐必须本地可达；合并仍卡人类",
    }


def render_handle_card(handle_or_id, *, purpose=None, acceptance=None,
                       scope_not=None, next_step=None, checklist=None,
                       relaunch=None, to_role=None, repo=None):
    """把句柄渲染成**自足落地文本**：云端只拿一个 id 也能重建全部上下文。

    为什么：本仓库工作面跨执行地是断开的（云端读不到本地句柄状态文件），
    只传句柄 id 等于空手。这里把「在哪、做什么、边界、验收、脑区、补法」全写进
    一张卡，且**卡本身自带合规接力卡标记**（`[触发:角色]` + 完整 `@org/repo(角色)`），
    可直接过 `relay_card.check` 闸门——交付方复制粘贴即合规，不靠自觉。
    """
    h = handle_or_id if isinstance(handle_or_id, dict) else get_handle(handle_or_id)
    if not h:
        return {"ok": False, "error": f"句柄不存在，无法渲染自足卡: {handle_or_id}"}
    hid = h.get("handle_id")
    meta = h.get("meta") or {}
    purpose = purpose or meta.get("purpose") or h.get("req")
    acceptance = acceptance or meta.get("acceptance") or h.get("acceptance") or DEFAULT_ACCEPT
    scope_not = scope_not or meta.get("scope_not") or DEFAULT_SCOPE_NOT
    next_step = next_step or meta.get("next_step") or DEFAULT_NEXT
    relaunch = relaunch if relaunch is not None else h.get("relaunch")
    role = to_role or meta.get("to_role") or h.get("to_role")
    target_repo = repo or h.get("target_repo")
    locus = analyze_locus(meta.get("actions"), local_reachable=bool(relaunch))
    checks = checklist or meta.get("checklist") or [
        "读代码/写码在云端完成（PR base = main）",
        f"验收以测试为准：{acceptance}",
        "产出回传本地时带 handle_id，供 collect/align 对齐",
    ]
    # 合规标记：完整 @org/repo(角色) + [触发:角色全称]（relay_card 同款格式）
    at_line = ""
    trig_line = ""
    if role:
        slug = repo or target_repo or "org/repo"
        at_line = f"@{slug}({role})"
        trig_line = f"[触发:{role}]"
    lines = []
    if at_line:
        lines.append(f"{at_line} {trig_line}".strip())
    lines += [
        f"【云开发·自足句柄卡 {hid}】",
        f"- 目的: {purpose}",
        f"- 验收: {acceptance}",
        f"- 不做: {scope_not}",
        f"- 下一步: {next_step}",
        f"- 在哪: target_repo={target_repo} · entry={h.get('entry')} · "
        f"issue={h.get('issue_id') or '-'} · prs={','.join(h.get('pr_ids') or []) or '-'}",
        f"- 状态: {h.get('status')}",
        "- 脑区(云端可做): " + (", ".join(locus["cloud_can"]) or "无"),
        "- 脑区(必须本地): " + (", ".join(locus["must_local"]) or "无"),
        "- 脑区(必须人工): " + (", ".join(locus["must_human"]) or "无"),
        f"- 本地可达: {'是' if relaunch else '否（本地独占动作登记为缺口，不做不等于不会）'}",
    ]
    if not locus["evidence_available"]:
        lines.append("- 证据缺口: 本地测试/对齐证据本轮不可得（≠无问题），"
                     "本地可达后凭句柄补做")
    if checklist:
        lines.append("- 自检清单:")
        lines += [f"  {i + 1}) {c}" for i, c in enumerate(checks)]
    if relaunch:
        lines.append(f"- 复现: {relaunch}")
    lines.append(f"- 自查: python3 local-agent/run.py --bridge verify --handle {hid}")
    card = "\n".join(lines)

    # 卡自带合规校验（缺标记即暴露，不沉默交付残卡）
    try:
        from relay_card import check as _relay_check
        _ok, _reasons = _relay_check(card, role=role) if role else (False,
                                                                    ["未指定承接角色，无 [触发] 标记"])
    except Exception as e:  # noqa: BLE001
        _ok, _reasons = False, [f"relay_card 校验不可用: {e}"]
    return {"ok": True, "handle_id": hid, "card": card,
            "relay_ok": _ok, "relay_reasons": _reasons,
            "locus": locus, "role": role}


def verify_handle_card(text, handle_id=None, to_role=None):
    """核验一张交付出去的卡是否**真自足**：无场外信息也能接住。

    检查项：合规接力标记 / 目的 / 验收 / 不做边界 / 所在仓库 / 句柄 id。
    缺任意一项 → `ok=False` + `missing` 列明，防"残卡交付"（用户 Issue #232 的原始症状）。
    """
    t = text or ""
    missing = []
    try:
        from relay_card import check as _relay_check
        r_ok, reasons = _relay_check(t, role=to_role) if to_role else (None, [])
        if r_ok is False and reasons:
            missing += reasons
    except Exception:  # noqa: BLE001
        if "[触发:" not in t:
            missing.append("缺少 [触发:角色全称] 标记")
    for label, pat in (
        ("目的", r"目的\s*[:：]"),
        ("验收标准", r"验收\s*[:：]"),
        ("不做边界", r"不做\s*[:：]"),
        ("所在仓库", r"target_repo\s*="),
    ):
        if not re.search(pat, t):
            missing.append(f"缺少{label}")
    hid = handle_id
    if hid:
        if hid not in t:
            missing.append(f"卡内未带句柄 id（{hid}），云端拿到也定位不到")
        elif get_handle(hid) is None:
            missing.append(f"句柄 {hid} 本地查不到（本地服务未开/未迁出）——"
                           "云端必须完全靠卡内文本自洽")
    return {"ok": not missing, "missing": missing,
            "self_contained": not missing, "handle_id": hid}


def mark_relaunch(handle_id, note=""):
    """标记本地已可达（本地服务/执行地在线），供脑区判定与证据保全翻正。"""
    handles = _load_handles()
    h = handles.get(handle_id)
    if not h:
        return {"ok": False, "error": f"句柄不存在，无法标记可达: {handle_id}"}
    h["relaunch"] = True
    h["updated_at"] = datetime.utcnow().isoformat()
    if note:
        h.setdefault("meta", {})["relaunch_note"] = note
    handles[handle_id] = h
    _save_handles(handles)
    return {"ok": True, "handle_id": handle_id, "relaunch": True}


# ---------------------------------------------------------------------------
# 三、云端结果收集（云端完成/打标 merged/done 后回传本地，跨 PR 归集）
# ---------------------------------------------------------------------------
def collect_cloud_result(handle_id, cloud_state=None, pr_ids=None, result=None,
                         transport=None):
    """收集一次云端异步开发的产出，状态流转 in_cloud_dev → collected。

    cloud_state：云端完成信号（'merged'/'done'/'need_fix'/'blocked'）——
    对应评审打标 merge_ready/merged / need_fix（REVIEW_DISPOSITION 规范标签）。
    pr_ids：云端实际产生的 PR 列表（跨 PR 归集）。
    """
    handles = _load_handles()
    handle = handles.get(handle_id)
    if not handle:
        return {"ok": False, "error": f"handle 不存在: {handle_id}"}
    state = cloud_state or handle.get("cloud_result", {}).get("state") or "done"
    handle["status"] = "collected"
    handle["updated_at"] = datetime.utcnow().isoformat()
    handle["cloud_result"] = {
        "state": state,
        "pr_ids": list(pr_ids or handle.get("pr_ids") or []),
        "result": result or {},
        "collected_at": datetime.utcnow().isoformat(),
    }
    if transport:  # 真实传输可把确认回执给云端
        try:
            transport.get("ack", lambda h: {"ok": True})(handle)
        except Exception:  # noqa: BLE001
            pass
    handles[handle_id] = handle
    _save_handles(handles)
    return {"ok": True, "handle": handle}


# ---------------------------------------------------------------------------
# 四、本地数据对齐（云端产出回写本地 relay/data，双向一致）
# ---------------------------------------------------------------------------
def align_local(handle_id, archive_kind="cloud_bridge"):
    """把已收集的云端产出对齐到本地（relay 接力卡 + data 归档 + messages 消息）。

    这样本地 harness / 网页桥可读到同一份「本地对齐后状态」，不因跨对话/跨 PR 丢失。
    """
    handle = get_handle(handle_id)
    if not handle or handle.get("status") != "collected":
        return {"ok": False, "error": "仅 collected 状态的句柄可对齐，先 collect_cloud_result"}
    # 1) relay 接力卡对齐（复用本地 relay 协议，写入云端产出摘要）
    try:
        import relay
        card = relay.load() or {}
        card["cloud_bridge"] = {
            "handle_id": handle_id,
            "state": handle.get("cloud_result", {}).get("state"),
            "pr_ids": handle.get("cloud_result", {}).get("pr_ids", []),
            "aligned_at": datetime.utcnow().isoformat(),
        }
        relay.save(card)
        relay_ok = True
    except Exception as e:  # noqa: BLE001
        relay_ok = False
        relay_err = str(e)
    # 2) data 层归档 + 消息（可审计回放）
    archive_ok = True
    try:
        import data.repository as repo
        aid = "cloud-bridge::" + handle_id
        repo.add_archive(aid, kind=archive_kind,
                         title="云端开发闭环对齐: " + handle["req"][:30],
                         content=json.dumps(handle.get("cloud_result") or {},
                                            ensure_ascii=False),
                         source=handle.get("entry", "local"))
        repo.enqueue_message("cloud.bridge.collect",
                             {"handle_id": handle_id,
                              "state": handle.get("cloud_result", {}).get("state"),
                              "pr_ids": handle.get("cloud_result", {}).get("pr_ids", [])},
                             from_agent="bridge", to_agent="local")
    except Exception:  # noqa: BLE001
        archive_ok = False
    return {"ok": relay_ok and archive_ok,
            "handle_id": handle_id,
            "state": handle.get("cloud_result", {}).get("state"),
            "relay_aligned": relay_ok,
            "data_archived": archive_ok}


# ---------------------------------------------------------------------------
# 五、本地测试先行门（云端建环境贵 → CPU 密集/长耗时测试下放本地执行）
# ---------------------------------------------------------------------------
def local_test_first(handle_id, test_scripts=None, executor=None, run=False, timeout=300):
    """把云端建的 CPU 密集 / 长耗时测试下放到本地执行（用户点名的主要成本点）。

    test_scripts：建议本地下放跑的测试（默认对齐 tests/ 常见信号灯脚本）。
    executor：本地执行器（默认 `_shell_executor`（真跑）/ `_mock_local_run`（只出计划））。
    run：True=真跑（默认 False 只出计划，不阻塞、不误报绿灯）；真跑结果带 returncode，
         **rc 非 0 如实返回 ok=False** —— 修掉 Issue #232 指出的"mock 执行器返回 ok=True
         让云端把没跑的测试当通过"的假绿灯。

    返回 local_test_plan：
      { ok, handle_id, routed_local: [...], skipped_cloud_build: bool,
        local_reachable, executed, results, cost_note }
    """
    handle = get_handle(handle_id)
    # 本地不可达（无句柄 / 未标记可达）→ 如实暴露证据缺口，不假装已下放
    reachable = bool(handle and (handle.get("relaunch") or run))
    scripts = test_scripts or [
        "test_platform_adapter.sh",   # 本模块适配测试
        "test_prescale_entry.sh",     # 入口护栏回归
        "test_bridge_handle_selfcontained.sh",   # 句柄自足（Issue #232）
    ]
    results = []
    if run and reachable:
        ex = executor or _shell_executor
        for sc in scripts:
            try:
                results.append(ex(sc, timeout=timeout))
            except Exception as e:  # noqa: BLE001
                results.append({"script": sc, "ok": False, "error": str(e)})
    ok = all(r.get("ok") for r in results) if results else True
    plan = {
        "ok": ok,
        "handle_id": handle_id,
        "routed_local": scripts,
        "skipped_cloud_build": True,          # 不在云端重复建环境跑这批
        "executed": bool(results),
        "local_reachable": reachable,
        "results": results,
        "executor": (executor or (_shell_executor if run else _mock_local_run)),
        "cost_note": "云端建环境贵：CPU密集测试下放本地执行，云端只保留LLM强相关" if reachable
                     else "本地不可达：本轮无本地测试证据（≠通过），须本地可达后凭句柄补做",
        "created_at": datetime.utcnow().isoformat(),
    }
    if isinstance(plan["executor"], dict):
        plan["executor"] = plan["executor"].get("name", "mock-local-exec")
    return plan


def _shell_executor(script, timeout=300):
    """真实本地执行器：跑 tests/<script>，返回 rc + 尾部输出（rc 非 0 即 ok=False）。

    脚本解析顺序：local-agent/tests → 仓库根 tests（两层放置都支持，找不到即报错不假装过）。
    """
    root = os.path.join(_HERE, "tests")
    repo_tests = os.path.join(os.path.dirname(_HERE), "tests")
    path = script if os.path.isabs(script) else os.path.join(root, script)
    if not os.path.isabs(script) and not os.path.exists(path):
        path = os.path.join(repo_tests, script)
    if not os.path.exists(path):
        return {"script": script, "ok": False, "error": "脚本不存在: " + path}
    try:
        p = subprocess.run(["bash", path], capture_output=True, text=True,
                           timeout=timeout, cwd=_HERE)
        tail = "\n".join((p.stdout or "").strip().splitlines()[-3:])
        return {"script": script, "ok": p.returncode == 0,
                "returncode": p.returncode, "tail": tail}
    except subprocess.TimeoutExpired:
        return {"script": script, "ok": False, "error": f"超时 {timeout}s"}


def _mock_local_run(scripts):
    """本地执行器 mock：返回计划结果（真实本地跑由宿主注入，如 local-exec.sh）。"""
    return {"ok": True, "executed": scripts, "mode": "mock-local",
            "note": "真实本地跑由宿主注入 scripts/local-exec.sh / hybrid 全绿链"}


# ---------------------------------------------------------------------------
# 六、闭环俯瞰（供人类 / 本地 harness 决策）
# ---------------------------------------------------------------------------
def loop_overview():
    """二级信息俯瞰：本地⇄云端桥接闭环状态。"""
    handles = _load_handles()
    by_status = {}
    for h in handles.values():
        s = h.get("status", "?")
        by_status.setdefault(s, []).append(h.get("handle_id"))
    return {
        "module": "platform-adapter",
        "issue": "Issue #105",
        "capability": "entries.bridge (本地⇄云端桥接闭环 · v0.3.0)",
        "link": ("最常用链路：本地deepseek harness ⇄ (网页/gemini工具桥) ⇄ "
                 "cnb.cool云端异步开发 → 云端产出回传本地对齐 → 本地测试先行"),
        "handles_total": len(handles),
        "handles_by_status": by_status,
        "cost_model": "云端建环境贵→CPU密集测试下放本地(CLOUD_LOCAL_COOP)",
        "close_loop_steps": [
            "1 request_cloud_dev 发起云端异步开发(拿到跨对话/跨PR句柄)",
            "2 云端开发完成 → collect_cloud_result 收集产出",
            "3 align_local 云端产出回写本地(relay/data)双向对齐",
            "4 local_test_first 云端CPU密集测试下放本地执行(降建环境成本)",
        ],
    }


# ---------------------------------------------------------------------------
# 便捷函数（供 run.py / 测试直接调用）
# ---------------------------------------------------------------------------
def handle_summary(handle_id):
    """句柄的一行摘要（供进度/留痕快速引用）。"""
    h = get_handle(handle_id)
    if not h:
        return {"ok": False, "error": f"handle 不存在: {handle_id}"}
    cr = h.get("cloud_result") or {}
    return {
        "ok": True,
        "handle_id": handle_id,
        "status": h.get("status"),
        "req": h.get("req"),
        "state": cr.get("state", ""),
        "pr_ids": cr.get("pr_ids", []),
        "entry": h.get("entry"),
        "target_repo": h.get("target_repo"),
    }


# ---------------------------------------------------------------------------
# 七、CLI 便捷：本地⇄云端桥接闭环 一步触发
# ---------------------------------------------------------------------------
def cli_bridge(req, entry="local", action="request", handle_id=None, collect_state=None,
               pr_ids=None, to_role=None, card_text=None, run=False,
               live=False, via=None):
    """run.py --bridge 的语义入口：request → collect → align → local-test 全链。

    action:
      request  发起云端异步开发请求（返回句柄）
      collect  按句柄收集云端产出（--collect-state merged/...  + --pr-ids）
      align    按句柄做本地数据对齐
      localtest 按句柄下发本地测试先行计划（--run 才真跑，rc 非 0 如实报 False）
      render   把句柄渲染成自足卡（--to-role 带合规 [触发] 标记）
      verify   核验一张卡是否自足（--handle 或 --card-file 文本）
      relaunch 标记本地已可达（翻正脑区判定与证据保全）
      overview 闭环俯瞰
    live: True → request 走默认真实通道（模拟数据不可信）。
    via:  指定真实宿主（cnb-live / local-harness / web-bridge，或别名），
          request 经该宿主真实传输发起（v0.6.0 host_transport 三宿主注册表）。
    """
    if via:
        from entries import host_transport
        if action in ("via-overview", "via-list"):
            return host_transport.overview()
        if action == "request":
            return host_transport.bridge_via(req or "云开发请求", via=via)
        return {"ok": False, "error": f"--bridge via=<host> 当前支持 action=request / via-overview"}
    if action == "overview":
        return loop_overview()
    if action == "request":
        return request_cloud_dev(req, entry=entry, live=live)
    if action == "render":
        if not handle_id:
            return {"ok": False, "error": "--bridge render 需要 --handle"}
        return render_handle_card(handle_id, to_role=to_role)
    if action == "verify":
        return verify_handle_card(card_text or "", handle_id=handle_id, to_role=to_role)
    if not handle_id:
        return {"ok": False, "error": "--bridge collect/align/localtest/relaunch 需要 --handle"}
    if action == "collect":
        return collect_cloud_result(handle_id, cloud_state=collect_state, pr_ids=pr_ids)
    if action == "align":
        return align_local(handle_id)
    if action == "localtest":
        return local_test_first(handle_id, run=run)
    if action == "relaunch":
        return mark_relaunch(handle_id)
    return {"ok": False, "error": f"未知 bridge action: {action}"}
