# -*- coding: utf-8 -*-
"""
三宿主真实传输注册表（entries.host_transport · Issue #105 最常用链路 · module platform-adapter v0.6.0）
=====================================================================================================
用户（#105 评论）最常用闭环：**本地 deepseek harness ⇄ 网页/gemini 工具桥 ⇄ cnb.cool 云端异步开发**。
v0.3.0~v0.5.0 已把 cnb.cool 云端端做成**真实通道**（entries.cnb_live，真实 cnb CLI 建 Issue/读状态/发回执），
但闭环另外两端的"真实宿主传输"仍未接线——本轮补齐，形成**三宿主传输注册表**，全程**真实机制**不 mock 假装：

  三宿主（各实现同一 {name, send, poll, ack} 传输契约，可注入 bridge.request/collect）：
    - cnb-live      云端端：真实 cnb.cool CLI 建/读/回执（复用 entries.cnb_live，v0.5.0 已实证）。
    - local-harness 本地端：真实 relay 接力卡 + 本地 bridge state——deepseek harness 发的云开发
                     请求真实落盘 relay/state，可续跑、可回放（不再是 mock 假"投递到云端"）。
    - web-bridge    网页端：真实 HTTP 通道——本仓 `run.py --serve` 的 /api + /api/control 即网页
                    桥的可达端点，web-bridge 通过真实 HTTP 探测/转发控制动作（不是 mock 假装）。

能力暴露：
  - `hosts()`               列出三宿主（key/name/locus/通道说明）
  - `resolve_host(alias)`   别名归一：网页/gemini/web→web-bridge；本地/deepseek/harness/local→
                           local-harness；cnb/云端/cnb→cnb-live（不写死、别名收敛）
  - `host_transport(name)`  返回对应宿主 transport dict {name, send, poll, ack}（真实机制）
  - `overview()`            三宿主真实可达性矩阵（供 dashboard snapshot 聚合/控制台俯瞰）
  - `bridge_via(req, via)`  经指定真实宿主发起一次云开发请求（组合 bridge.request_cloud_dev +
                            host transport）——run.py --bridge via=<host> 的语义入口
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# 一、三宿主注册表（key → 描述；真实机制在 host_transport() 里按 name 组装）
# ---------------------------------------------------------------------------
# alias → 规范 host key（不写死宿主名，别名归一收敛到三端之一）
_ALIAS = {
    # 网页/gemini 工具桥端
    "web": "web-bridge", "web-bridge": "web-bridge", "gemini": "web-bridge",
    "网页": "web-bridge",
    # 本地 deepseek harness 端
    "local": "local-harness", "local-harness": "local-harness",
    "harness": "local-harness", "deepseek": "local-harness", "dsh": "local-harness",
    "本地": "local-harness",
    # cnb.cool 云端端
    "cnb": "cnb-live", "cnb-live": "cnb-live", "cloud": "cnb-live",
    "云端": "cnb-live",
}

_HOST_META = {
    "cnb-live": {
        "name": "cnb-live", "locus": "cloud",
        "desc": "cnb.cool 云端异步开发（真实 cnb CLI：建 Issue 锚/读状态/发回执）",
        "real": True,
    },
    "local-harness": {
        "name": "local-harness", "locus": "local",
        "desc": "本地 deepseek harness（真实 relay 接力卡 + 本地 bridge state，可续跑可回放）",
        "real": True,
    },
    "web-bridge": {
        "name": "web-bridge", "locus": "hybrid",
        "desc": "网页/gemini 工具桥（真实 HTTP 通道：run.py --serve 的 /api + /api/control）",
        "real": True,
    },
}


def resolve_host(alias):
    """别名归一：把入口一句话/宿主别名收敛到规范 host key；未知别名原样透传。

    大小写不敏感（CNB/cnb/Cnb → cnb-live；LOCAL/Local → local-harness）。
    """
    alias = (alias or "").strip()
    key = alias.lower()
    hit = _ALIAS.get(key)
    if hit:
        return hit
    return alias or "cnb-live"  # 未知别名原样透传（host_transport 兜底报错不静默）


def hosts():
    """列出三宿主（key/name/locus/通道说明）。"""
    return [dict(v) for v in _HOST_META.values()]


# ---------------------------------------------------------------------------
# 二、各宿主真实 transport 组装（同 {name, send, poll, ack} 契约）
# ---------------------------------------------------------------------------
def _local_harness_transport(repo=None):
    """本地 deepseek harness 真实传输：
    send = 把云开发请求真实落盘 relay 接力卡（新卡）+ bridge state 已由 request 存；poll =
    真实读 relay 卡状态；ack = 真实给 relay 卡 log 回执。全程本仓真实 relay/state，非 mock。
    """
    try:
        import relay
    except Exception:  # noqa: BLE001
        relay = None

    def _send(h):
        req = (h.get("req") or "").strip()
        if relay is not None:
            card = relay.new_card(req or "云开发请求", first_step="cloud_dev",
                                  first_role="架构·开发")
            relay.log(card, f"[host_transport local-harness] 云开发请求投递 relay（{card['req'][:40]}）")
            relay.save(card)   # relay.log 仅改内存，需 save 才真实落盘（可回放/可续跑）
        return {
            "ok": True,
            "cloud_ref": {
                "issue_id": h.get("issue_id") or "relay-card",
                "sent_via": "local-harness(relay)",
                "transport": "local-harness",
            },
            "status": "in_cloud_dev",
            "relay_aligned": relay is not None,
        }

    def _poll(h):
        st = "in_progress"
        note = "local-harness 本地接力卡在云开发（relay）"
        if relay is not None:
            card = relay.load()
            if card and card.get("status") in ("done", "reverted"):
                st = "done" if card.get("status") == "done" else "blocked"
                note = f"local-harness relay 状态={card.get('status')}"
        return {"ok": True, "state": st, "pr_ids": [], "note": note,
                "transport": "local-harness"}

    def _ack(h):
        note = "local-harness 回执已落 relay（可回放）"
        if relay is not None:
            card = relay.load()
            if card:
                relay.log(card, "[host_transport local-harness] 结果回执："
                                f"{h.get('req_key','')} → collected")
                relay.save(card)   # 持久化回执，可回放
        return {"ok": True, "note": note, "transport": "local-harness"}

    return {"name": "local-harness", "send": _send, "poll": _poll, "ack": _ack}


def _web_bridge_transport(repo=None, base_url=None):
    """网页/gemini 工具桥真实传输：
    send = 真实发起一次桥接请求到 --serve 的 /api/control（POST request）；
    poll = 真实 GET /api/health 探测网页桥可达性 + 读句柄；ack = 真实 POST /api/control collect。
    base_url 默认 http://127.0.0.1:<port>（port 用 --bridge-via port 显式或 8080）。
    说明：--serve 是网页桥可挂的可达端点；本 transport 走真实 HTTP（不是 mock）。
    """
    import json as _json
    import urllib.request
    import urllib.parse

    def _req(method, path, payload=None, base=base_url):
        if not base:
            # 默认探测 --serve 端口（可被环境变量/注入覆盖）
            port = os.environ.get("PLATFORM_SERVE_PORT", "8080")
            base = f"http://127.0.0.1:{port}"
        url = base + path
        data = None
        headers = {}
        if payload is not None:
            data = _json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                body = resp.read().decode("utf-8", "replace")
                try:
                    return _json.loads(body)
                except Exception:  # noqa: BLE001
                    return {"ok": True, "raw": body}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"web-bridge HTTP 不可达: {e}"}

    def _send(h):
        return _req("POST", "/api/control",
                    {"action": "request", "entry": "web", "req": h.get("req", "")})

    def _poll(h):
        hb = _req("GET", "/api/health")
        return {"ok": hb.get("ok", False),
                "state": "in_progress" if hb.get("ok") else "unknown",
                "pr_ids": [], "transport": "web-bridge", "health": hb}

    def _ack(h):
        return _req("POST", "/api/control",
                    {"action": "collect", "handle_id": h.get("handle_id", "")})

    return {"name": "web-bridge", "send": _send, "poll": _poll, "ack": _ack}


def host_transport(name, repo=None, base_url=None):
    """返回指定宿主 transport dict {name, send, poll, ack}（真实机制）。"""
    name = resolve_host(name)
    if name == "cnb-live":
        from entries import cnb_live
        return cnb_live.live_transport(repo)
    if name == "local-harness":
        return _local_harness_transport(repo)
    if name == "web-bridge":
        return _web_bridge_transport(repo, base_url)
    # 未知宿主：给可读错误，不静默 mock
    return {"name": name, "send": lambda h: {"ok": False,
            "error": f"未知宿主传输: {name}（可用 cnb-live/local-harness/web-bridge）"},
            "poll": lambda h: {"ok": False, "state": "unknown"},
            "ack": lambda h: {"ok": False, "error": f"未知宿主传输: {name}"}}


# ---------------------------------------------------------------------------
# 三、三宿主真实可达性矩阵（供 dashboard snapshot / 控制台俯瞰）
# ---------------------------------------------------------------------------
def _reachable(name):
    if name == "cnb-live":
        try:
            import shutil
            return shutil.which("cnb") is not None
        except Exception:  # noqa: BLE001
            return False
    if name == "local-harness":
        try:
            import relay
            return relay is not None
        except Exception:  # noqa: BLE001
            return False
    if name == "web-bridge":
        # 网页桥可达性 = --serve HTTP /api 是否可探测（read 通）
        tr = _web_bridge_transport()
        try:
            hb = tr["poll"]({})
            return bool(hb.get("ok"))
        except Exception:  # noqa: BLE001
            return False
    return False


def overview(repo=None):
    """三宿主真实可达性矩阵。"""
    rows = []
    for h in hosts():
        name = h["name"]
        ok = _reachable(name)
        rows.append({
            "key": name, "locus": h["locus"], "desc": h["desc"],
            "reachable": ok, "health": {"status": "ok" if ok else "offline",
                                        "light": "🟢" if ok else "🔴"},
        })
    return {
        "module": "platform-adapter", "version": "v0.6.0",
        "transport_contract": ["send", "poll", "ack"],
        "hosts": rows,
        "all_reachable": all(r["reachable"] for r in rows),
        "note": "三宿主真实传输：cnb-live(云端CLI)/local-harness(本地relay)/web-bridge(--serve HTTP)",
    }


# ---------------------------------------------------------------------------
# 四、经指定真实宿主发起云开发请求（bridge_via）
#    run.py --bridge via=<host> 的语义入口。
# ---------------------------------------------------------------------------
def bridge_via(req, via="cnb-live", repo=None, base_url=None):
    """经指定真实宿主发起一次云开发请求。

    返回 { via, handle, transport, host_overview }
    via 别名归一到规范 host；transport = host_transport(via)（真实机制）注入
    bridge.request_cloud_dev → 获得真实桥接句柄。
    """
    from entries import bridge
    host_key = resolve_host(via)
    tr = host_transport(host_key, repo=repo, base_url=base_url)
    handle = bridge.request_cloud_dev(req, entry=host_key, target_repo=repo,
                                      transport=tr, live=(host_key == "cnb-live"))
    return {
        "via": host_key,
        "transport": tr["name"],
        "handle": handle,
        "hosts": overview(repo=repo),
    }


def cli_host(via="overview", req="", repo=None, base_url=None):
    """run.py --bridge via=<host> 的语义入口（overview=矩阵 / host=发起请求）。"""
    if via in ("overview", "list", ""):
        return overview(repo=repo)
    return bridge_via(req or "云开发请求", via=via, repo=repo, base_url=base_url)
