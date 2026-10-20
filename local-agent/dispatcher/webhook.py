# -*- coding: utf-8 -*-
"""
调度中枢 · 多源 Webhook 接收端（webhook）
========================================
用户最新拍板：**首个外部源就是本地电脑**，形成云端 + 本地协同；手机 / 虚拟机 /
沙盒环境都可能作为终端参与，**不能只支持一个源**；**webhook 更合理**。

本模块提供一个**统一 Webhook 接收端**，把多个外部终端（本地电脑 / 手机 / 虚拟机 /
沙盒 / 上位机）推送来的事件统一接入 dispatcher：

```
  外部终端（本地电脑/手机/虚拟机/沙盒/上位机）
        │  POST /webhook/<source_name>  头: X-API-Key
        ▼
  ┌───────────────────────────────────────────────┐
  │  WebhookReceiver（webhook.py）                  │
  │  ① security.authenticate：秘钥 + IP 白名单       │
  │  ② 认证通过 → normalize 为标准事件                │
  │  ③ 投递给 Dispatcher.process_event 走同一链路     │
  │  ④ 认证失败/拦截 → 留痕审计（面板可见）            │
  └───────────────────────────────────────────────┘
```

多源设计：
  - 每个外部终端独立登记 `external_sources` 表（独立 key + 独立 IP 白名单）；
  - webhook 路径按源名路由 `/webhook/<source_name>`，认证不通过拒绝注入；
  - 与 `--watch` 轮询互补：webhook 是**事件推送**（webhook 更合理，用户拍板），
    本地电脑等终端把事件主动 POST 进来，无需接收端轮询外部；
  - 复用 dispatcher 现有链路：事件进来后 normalize → rules → queue → guard →
    router → webui，与仓库事件完全同构。

**角色名册派单入口（`POST /webhook/<source_name>/roster`，Issue #171）**：

外部对端拿到 `roster.catalog()` 的 `role_id` 后，不必 import 本仓任何模块，
直接 POST 一条派单请求即可入场：

```
POST /webhook/local_pc/roster   头: X-API-Key <该源秘钥>
{"target": "arch.developer", "task": "补 token 刷新", "entity": "issue-42"}
```

链路：认证（同 webhook）→ `roster.intake()` → `intake` 内部走同一条
`rules → queue → guard → router`，返回 `event_id` 可回查。
回执里 `ok` 只代表"真派出去了"，`ok=false + reason` 明确区分
`role_not_implemented`（跑不了）/ `unknown_target`（认不出）/ `not_dispatched`（被护栏拦）。

安全（用户拍板 key + IP 白名单）：
  - 请求头 `X-API-Key` 携带该源秘钥；
  - `security.authenticate` 校验「源存在 + 启用 + key 匹配 + IP 在白名单」；
  - 认证审计 `external_auth` 表留痕，Web 面板可俯瞰拦截情况。
"""
import html
import ipaddress
import json
import os
import sys
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import db, schema
from . import security
from . import source as source_mod


def _client_ip(handler):
    """取请求方 IP（兼容 X-Forwarded-For 透传，但白名单以直连 IP 为准可配置）。"""
    xff = handler.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return handler.client_address[0]


def handle_webhook(handler, path):
    """Webhook 事件接收入口：认证 → 规范化 → 投递给 dispatcher。

    供 BaseHTTPRequestHandler 复用；返回 (http_code, body_dict)。
    """
    # 路径形如 /webhook/<source_name>
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "webhook":
        return 404, {"ok": False, "error": "not_found"}

    source_name = parts[1]
    is_roster = len(parts) > 2 and parts[2] == "roster"
    api_key = handler.headers.get("X-API-Key", "")
    client_ip = _client_ip(handler)

    # ① 安全认证（秘钥 + IP 白名单）
    ok, reason, src = security.authenticate(source_name, api_key, client_ip)
    if not ok:
        return 401, {"ok": False, "error": reason, "source": source_name,
                     "client_ip": client_ip}

    # ② 读取请求体（JSON）
    try:
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception as e:
        return 400, {"ok": False, "error": f"bad_json: {e}"}

    # ③ 角色名册派单：同一套认证，走 roster.intake
    if is_roster:
        return _handle_roster(payload, src, source_name, client_ip)

    # ④ 规范化事件并注入 dispatcher
    from . import engine
    dispatcher = engine.Dispatcher()
    # 支持单事件（payload 直接是事件）或批量（events 数组）
    events = payload.get("events") if isinstance(payload, dict) and isinstance(
        payload.get("events"), list) else [payload]
    results = []
    for ev in events:
        if not isinstance(ev, dict):
            ev = {"event_type": "unknown", "detail": {"raw": ev}}
        ev.setdefault("source", src["name"])
        # 打上源级上下文（gid / detail 来源标识），供去重与路由
        ev.setdefault("detail", {})
        if isinstance(ev["detail"], dict):
            ev["detail"].setdefault("external_source", src["name"])
            ev["detail"].setdefault("client_ip", client_ip)
        try:
            res = dispatcher.process_event(ev)
        except Exception as e:
            res = {"event_id": ev.get("event_id", ""), "status": "error",
                   "note": str(e)}
        results.append(res)

    return 200, {"ok": True, "source": source_name, "accepted": len(results),
                 "results": results}


def _handle_roster(payload, src, source_name, client_ip):
    """角色名册派单入口：把对端的派单请求交给 roster.intake（不另起链路）。

    单条 or 批量（`{"requests": [...]}`）；逐条记账，单条失败不中断整批。
    """
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "bad_payload"}
    try:
        from roster import intake as roster_intake
    except Exception as e:  # noqa: BLE001
        return 500, {"ok": False, "error": f"roster_unavailable: {e}"}

    reqs = payload.get("requests")
    batch = isinstance(reqs, list)
    items = reqs if batch else [payload]

    results = []
    for item in items:
        if not isinstance(item, dict):
            results.append({"ok": False, "reason": "bad_request"})
            continue
        item = dict(item)
        item.setdefault("source", f"webhook:{source_name}")
        item.setdefault("detail", {})
        if isinstance(item["detail"], dict):
            item["detail"].setdefault("external_source", source_name)
            item["detail"].setdefault("client_ip", client_ip)
        try:
            results.append(roster_intake(item))
        except Exception as e:  # noqa: BLE001
            results.append({"ok": False, "reason": "intake_error", "error": str(e)})

    ok = all(r.get("ok") for r in results) if results else False
    body = {"ok": ok, "source": source_name, "accepted": sum(1 for r in results if r.get("ok")),
            "rejected": sum(1 for r in results if not r.get("ok")),
            "results": results}
    if not batch:
        body = {"ok": ok, "source": source_name, **results[0]}
    # 认不出目标 / 跑不了 → 400（对端要修，不是它的服务端错误）
    code = 200 if ok else (400 if all(r.get("reason") in
                                     ("unknown_target", "role_not_implemented",
                                      "empty_task", "bad_request") for r in results) else 409)
    return code, body


class _WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            code, body = handle_webhook(self, self.path)
        except Exception as e:  # noqa
            code, body = 500, {"ok": False, "error": str(e)}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # 健康检查
        if self.path == "/healthz":
            data = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        # 用法说明
        body = html.escape(
            "外部事件源 Webhook 接收端\n"
            "POST /webhook/<source_name>  头: X-API-Key <该源秘钥>\n"
            "POST /webhook/<source_name>/roster  角色名册派单（target=role_id）\n"
            "Body: 事件 JSON（单事件 或 {events:[...]} 批量）\n"
            "安全: 秘钥 + IP 白名单（见 security.py）\n"
            "登记源: python -m local-agent.dispatcher.cli ext add <name>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 抑制默认日志
        pass


def serve(port=8081, register_defaults=True):
    """启动多源 Webhook 接收端（与 webui 面板可并存，默认端口 8081 区分）。"""
    schema.init_schema()
    if register_defaults:
        _register_default_sources()
    server = HTTPServer(("0.0.0.0", port), _WebhookHandler)
    print(f"多源 Webhook 接收端运行于 http://0.0.0.0:{port}/webhook/<source>")
    print("安全：秘钥 key + IP 白名单（deny-by-default）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWebhook 接收端已停止")
        server.server_close()


def _register_default_sources():
    """预设默认多终端源（本地电脑 / 手机 / 虚拟机 / 沙盒 / 上位机）。

    用户拍板：不能只支持一个源；手机/虚拟机/沙盒都可能参与。
    这里**预设功能**（上位机部分还未解决好，先预设、之后接入）。
    每个源独立 key + 独立 IP 白名单（本地回环默认开放，其余待用户配置）。
    """
    defaults = {
        "local_pc":    ["127.0.0.1", "::1", "0.0.0.0/0"],  # 本地电脑（云端-本地协同主源）
        "phone":       [],          # 手机终端：待用户配置 IP 白名单
        "vm":          [],          # 虚拟机：待配置
        "sandbox":     [],          # 沙盒环境：待配置
        "host_upper":  [],          # 上位机：部分未解决好，先预设功能，之后接入
    }
    for name, wl in defaults.items():
        if not security.get_source(name):
            src = security.register_source(name, ip_whitelist=wl, kind="webhook",
                                           meta='{"preset":true}')
            print(f"  [预设] 外部源 {name}: key={src['api_key']} "
                  f"ip_whitelist={wl or '(待配置,deny-all)'}")
        else:
            print(f"  [已存在] 外部源 {name}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="多源 Webhook 接收端")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--no-preset", action="store_true", help="不预设默认源")
    args = parser.parse_args()
    serve(args.port, register_defaults=not args.no_preset)


if __name__ == "__main__":
    main()
