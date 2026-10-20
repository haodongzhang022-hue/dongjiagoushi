# -*- coding: utf-8 -*-
"""
MCP 汇聚注册表 · 统一入口（三前端一处语义）
============================================
一个进程一个端口，前端只差一层皮：

  GET  /health                    三前端都可用（有旧客户端可能不理解 POST，给个无副作用的 GET）
  POST /message                   默认文本端点：{tool, params, operator} 或 JSON-RPC
  GET  /sse  → POST /message      事件流：GET 收服务端通知，POST 发请求（带 session）
  POST /jsonrpc                   规范线：JSON-RPC 2.0 的 MCP 帧

**一处语义**：三个前端最终都走 `mcp_hub.dispatch.call()`，不存在「http 能调、sse 调不了」
这种分叉；前端差异只在帧格式与传输方式，能力集合完全一致（`fronts` 三元 + 工具清单由
`specs.py` 决定）。

无状态优先：`message` / `sse` 两端点不需要 initialize 握手（见 docs/MCP_HUB.md 决策①），
旧客户端只发 POST 也能用；`jsonrpc` 端点按规范回 `initialize` 结果，不做鉴权
（本 hub 是**本机入网口**，签名/秘钥留给上层的 dispatcher webhook）。
"""
import json
import os
import sys
import uuid

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from . import dispatch, specs

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "dongjiagoushi-mcp-hub", "version": "0.1.0"}


def tool_list():
    """MCP tools/list 形态（name / description / inputSchema）。"""
    out = []
    for ep in specs.ENDPOINTS:
        for name in ep["tools"]:
            out.append({
                "name": name,
                "description": f"{ep['name']} · {ep['note']}",
                "inputSchema": {"type": "object", "additionalProperties": True},
                "x-endpoint": ep["id"],
                "x-kind": ep["kind"],
            })
    return out


def handle_tool_call(name, arguments, operator=None):
    return dispatch.call(name, arguments or {}, operator=operator)


# ---------------------------------------------------------------- 三前端共用
def handle_message(payload, operator=None):
    """默认文本端点语义。兼容两种 body：

      {"tool": "relay.check", "params": {...}, "operator": "架构·开发"}
      {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}
    """
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "bad_payload"}
    if payload.get("jsonrpc") == "2.0" or "method" in payload:
        return jsonrpc_body(payload, operator=operator)

    tool = payload.get("tool", "")
    if tool in ("tools/list", ""):
        return {"ok": True, "data": {"tools": tool_list()}}
    if tool == "tools/call":
        inner = payload.get("params") or {}
        return handle_tool_call(inner.get("name", ""), inner.get("arguments") or {},
                                operator=payload.get("operator") or operator)
    return handle_tool_call(tool, payload.get("params") or {},
                            operator=payload.get("operator") or operator)


def jsonrpc_body(payload, operator=None):
    """JSON-RPC 2.0 帧（MCP 规范线）。返回完整响应体（含 jsonrpc/id）。"""
    rid = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list()}}
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/call":
        res = handle_tool_call(params.get("name", ""), params.get("arguments") or {},
                               operator=params.get("operator") or operator)
        if res.get("ok"):
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text",
                                            "text": json.dumps(res.get("data"),
                                                               ensure_ascii=False)}],
                               "isError": False}}
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(res, ensure_ascii=False)}],
                           "isError": True}}
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


# ---------------------------------------------------------------- HTTP 服务
def make_handler(operator_default=None):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        server_version = "mcp-hub/0.1.0"

        def _reply(self, code, obj, ctype="application/json; charset=utf-8"):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/health", "/"):
                self._reply(200, {"ok": True, "server": SERVER_INFO,
                                  "parts": specs.FRONTS,
                                  "endpoints": [e["id"] for e in specs.ENDPOINTS],
                                  "tool_count": len(tool_list())})
                return
            if path == "/sse":
                self._sse()
                return
            self._reply(404, {"ok": False, "reason": "not_found"})

        def _sse(self):
            """SSE 前端：先推 endpoint 事件，再等客户端 POST /message 发请求。"""
            session = uuid.uuid4().hex
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(
                    f"event: endpoint\ndata: /message?session={session}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                payload = self._read_json()
            except Exception as e:  # noqa: BLE001
                self._reply(400, {"ok": False, "reason": f"bad_json: {e}"})
                return

            if path in ("/message", "/sse"):
                res = handle_message(payload, operator=operator_default)
                self._reply(200 if res.get("ok") else 200, res)
                return
            if path == "/jsonrpc":
                self._reply(200, jsonrpc_body(payload, operator=operator_default))
                return
            self._reply(404, {"ok": False, "reason": "not_found"})

        def log_message(self, *a):
            pass

    return Handler


def serve(port=3092, host="127.0.0.1", operator=None):
    """起 MCP 汇聚服务。端口建议值集中只在 `specs`/CLI 里出现一次。"""
    from http.server import HTTPServer

    server = HTTPServer((host, port), make_handler(operator))
    print(f"[mcp-hub] 汇聚服务: http://{host}:{port}"
          f"  (GET /health · POST /message · GET /sse · POST /jsonrpc)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return server
