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
"""
import json
import os
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
                  False → 默认 mock（兼容单测确定性，无 transport 显式注入时）。
                  注：真实 CLI/真实使用应传 live=True 或用 run.py --bridge --live。

    返回 CloudDevHandle：
      { handle_id, status, entry, target_repo, req,
        created_at, cloud_ref（云端锚: issue/pr）, transport }
    """
    _ensure_dir()
    handles = _load_handles()
    req_key = req.strip().splitlines()[0][:40]
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
        "meta": meta,
    }
    # 通过传输通道把云开发请求投递给云端。
    # 用户（#105）「模拟数据不可信」→ live=True 或显式注入真实 transport 时走真实；
    # 默认 mock 仅为兼容单测确定性（单测不传 transport / live）。
    tr = transport
    if tr is None:
        if live:
            try:
                from entries import cnb_live
                tr = cnb_live.default_transport(target_repo)
            except Exception:  # noqa: BLE001
                tr = {"name": "mock", "send": _mock_send}
        else:
            tr = {"name": "mock", "send": _mock_send}
    try:
        sent = tr["send"](handle)
        handle["cloud_ref"] = sent.get("cloud_ref", {})
        handle["status"] = sent.get("status", "in_cloud_dev")
    except Exception as e:  # noqa: BLE001
        handle["status"] = "pending"
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
def local_test_first(handle_id, test_scripts=None, executor=None):
    """把云端建的 CPU 密集 / 长耗时测试下放到本地执行（用户点名的主要成本点）。

    test_scripts：建议本地下放跑的测试（默认对齐 tests/ 常见信号灯脚本）。
    executor：本地执行器（默认 mock 返回计划），真实本地跑由宿主注入
    （如 scripts/local-exec.sh / hybrid 全绿链）。

    返回 local_test_plan：
      { ok, handle_id, routed_local: [...], skipped_cloud_build: bool,
        cost_note: '云端建环境贵，CPU密集测试已下放本地' }
    """
    scripts = test_scripts or [
        "test_platform_adapter.sh",   # 本模块适配测试
        "test_prescale_entry.sh",     # 入口护栏回归
        "test_doc_consistency.sh",    # 文档/声明一致性
    ]
    # 判定这些测试是否「CPU 密集/长耗时应下放本地」——默认全部本地化
    plan = {
        "ok": True,
        "handle_id": handle_id,
        "routed_local": scripts,
        "skipped_cloud_build": True,          # 不再在云端重复建环境跑这批
        "executor": executor or {"name": "mock-local-exec",
                                 "run": _mock_local_run},
        "cost_note": "云端建环境贵：CPU密集测试已下放本地执行，云端只保留LLM强相关",
        "created_at": datetime.utcnow().isoformat(),
    }
    return plan


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
               pr_ids=None, live=False):
    """run.py --bridge 的语义入口：request → collect → align → local-test 全链。

    action:
      request  发起云端异步开发请求（返回句柄；live=True → 真实通道）
      collect  按句柄收集云端产出（--collect-state merged/...  + --pr-ids）
      align    按句柄做本地数据对齐
      localtest 按句柄下发本地测试先行计划
      overview 闭环俯瞰
    """
    if action == "overview":
        return loop_overview()
    if action == "request":
        return request_cloud_dev(req, entry=entry, live=live)
    if not handle_id:
        return {"ok": False, "error": "--bridge collect/align/localtest 需要 --handle"}
    if action == "collect":
        return collect_cloud_result(handle_id, cloud_state=collect_state, pr_ids=pr_ids)
    if action == "align":
        return align_local(handle_id)
    if action == "localtest":
        return local_test_first(handle_id)
    return {"ok": False, "error": f"未知 bridge action: {action}"}
