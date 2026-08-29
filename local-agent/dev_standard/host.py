# -*- coding: utf-8 -*-
"""
开发规范 · MCP 宿主接入层（dev-standard · host.py · Issue #83 / M5）
=======================================================================
把 `standard.*` MCP 工具**真正接入可运行宿主**，让外部宿主（cnb.cool 流水线 /
deepseek harness / CLI / 任意 agent 运行时 / HTTP 客户端）能程序化调用开发规范能力，
形成完整的"MCP 宿主接入"闭环（延续 M5 里程碑）。

对齐用户拍板（Issue #83）：
  - **解除耦合是对的**：host 层是**薄适配器**，所有逻辑收口到 `StandardAbility` /
    `call_mcp`，不重复实现规范逻辑；
  - **调用的形式比较好**：以 `standard.*` MCP 工具名为调用契约，宿主注册工具清单 +
    按名调用，与 label / dispatcher 宿主模式一致；
  - **本身是体系**：注册层（register_tools）+ 调用层（call）+ JSON host 服务层
    （serve，供 HTTP 客户端/CI 远程调用）+ CLI 入口，四处贯通。

本模块提供：
  - StandardMCPHost   宿主适配器（register_tools / call / overview / serve）
  - StandardHTTPServer JSON host（POST /rpc，body={tool,params} → {ok,data}）
  - main()            CLI 入口（list / call / serve）
"""
import json
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from dev_standard import mcp as mcp_mod


class StandardMCPHost:
    """开发规范 MCP 宿主适配器。

    供外部宿主统一接入 `standard.*` 工具：注册工具清单 + 按名调用，所有逻辑
    收口到 `dev_standard.mcp.call_mcp`（→ StandardAbility），本层只做路由与分发。
    """

    def __init__(self, operator="系统"):
        self.operator = operator
        self.tools = {t["name"]: t for t in mcp_mod.MCP_TOOLS}

    # ---- 注册层（宿主向外部暴露工具清单）----
    def register_tools(self):
        """返回可注册的 `standard.*` MCP 工具清单（供宿主/agent 运行时注册）。"""
        return [dict(t) for t in mcp_mod.MCP_TOOLS]

    def list_tools(self):
        """工具名清单（含描述），供宿主/人类俯瞰。"""
        return [
            {"name": t["name"], "description": t.get("description", "")}
            for t in self.tools.values()
        ]

    # ---- 调用层（按名调用）----
    def call(self, tool_name, params=None, operator=None):
        """按 `standard.*` 工具名调用，返回标准化响应 {ok, data/error}。"""
        op = operator or self.operator
        if tool_name not in self.tools:
            return {"ok": False, "error": f"未知标准工具 {tool_name}",
                    "available": [n for n in self.tools]}
        return mcp_mod.call_mcp(tool_name, params or {}, operator=op)

    # ---- 俯瞰层（二级信息）----
    def overview(self):
        """宿主接入概览：工具清单 + 规范注册表摘要。"""
        from dev_standard import StandardAbility
        ab = StandardAbility(owner=self.operator)
        return {
            "host": "dev-standard/mcp-host",
            "operator": self.operator,
            "tools": self.list_tools(),
            "tool_count": len(self.tools),
            "specs": ab.standards_summary(),
        }

    # ---- JSON host 服务层 ----
    def serve(self, port=8701, host="0.0.0.0"):
        """起一个 JSON host 服务，POST /rpc 即可调用 `standard.*` 工具。"""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def _reply(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    tool = payload.get("tool", "")
                    params = payload.get("params", {}) or {}
                    op = payload.get("operator") or self.operator
                except Exception as e:  # noqa
                    self._reply(400, {"ok": False, "error": f"请求解析失败: {e}"})
                    return
                result = self.call(tool, params, operator=op)
                code = 200 if result.get("ok") else 422
                self._reply(code, result)

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, {"ok": True, "service": "dev-standard/mcp-host"})
                elif self.path == "/tools":
                    self._reply(200, {"ok": True, "data": self.list_tools()})
                else:
                    self._reply(404, {"ok": False, "error": "not found"})

        server = HTTPServer((host, port), _Handler)
        print(f"[standard-host] MCP JSON host 已启动: http://{host}:{port} "
              f"(POST /rpc, GET /health /tools)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
        return server


def serve(port=8701, host="0.0.0.0"):
    """便捷函数：起 dev-standard MCP JSON host 服务。"""
    return StandardMCPHost().serve(port=port, host=host)


def main(argv=None):
    """CLI 入口：list / call / serve。

    用法：
      python -m dev_standard.host list                     # 宿主工具清单
      python -m dev_standard.host call standard.summary '{}'
      python -m dev_standard.host call standard.enforced '{"stage":"pre_pr"}'
      python -m dev_standard.host overview                 # 宿主接入概览
      python -m dev_standard.host serve --port 8701        # 起 JSON host 服务
    """
    import argparse
    p = argparse.ArgumentParser(prog="dev_standard.host", description="开发规范 MCP 宿主")
    p.add_argument("cmd", choices=["list", "call", "overview", "serve"], nargs="?",
                   default="overview")
    p.add_argument("tool", nargs="?", default="", help="call 时：standard.* 工具名")
    p.add_argument("params", nargs="?", default="{}", help="call 时：params JSON")
    p.add_argument("--operator", default="系统")
    p.add_argument("--port", type=int, default=8701)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args(argv)

    host = StandardMCPHost(operator=args.operator)
    if args.cmd == "list":
        print(json.dumps(host.list_tools(), ensure_ascii=False, indent=2))
    elif args.cmd == "call":
        try:
            params = json.loads(args.params)
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"params JSON 解析失败: {e}"}))
            return 1
        print(json.dumps(host.call(args.tool, params), ensure_ascii=False, indent=2))
    elif args.cmd == "overview":
        print(json.dumps(host.overview(), ensure_ascii=False, indent=2))
    elif args.cmd == "serve":
        host.serve(port=args.port, host=args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
