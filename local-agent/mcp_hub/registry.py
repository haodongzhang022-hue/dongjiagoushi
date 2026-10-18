# -*- coding: utf-8 -*-
"""
MCP 汇聚注册表 · 握手与探活
===========================
`catalog()` 回答「有哪些端点、哪些工具、现在跑没跑起来」。
`launch()` 回答「我现在要一个能用的 MCP 服务」——**服务拉起与探活回执属于同一个请求**，
不是两件事：探测到已在跑就复用（`reused=true`），没在跑就真起一个（`started=true`），
起不来就如实 `started=false + reason`，不返回看着成功的空壳。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(_LOCAL_AGENT_DIR)
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from . import specs
from .server import SERVER_INFO, tool_list

STATE_DIR = os.path.join(_LOCAL_AGENT_DIR, "mcp_hub", "_runtime")
LOG_FILE = os.path.join(STATE_DIR, "serve.log")
PID_FILE = os.path.join(STATE_DIR, "serve.pid")


def _health(port, host="127.0.0.1", timeout=1.5):
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, data
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, {"error": f"{type(e).__name__}: {e}"}


def _port_taken(port, host="127.0.0.1", timeout=0.5):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def status(port=3092, host="127.0.0.1"):
    """探活单个端点（不启动任何东西）。"""
    alive, detail = _health(port, host)
    return {"url": f"http://{host}:{port}", "alive": alive, "health": detail}


def catalog(port=3092, host="127.0.0.1", probe=True):
    """握手：端点清单 + 工具清单 + 是否可达。"""
    data = {
        "server": SERVER_INFO,
        "fronts": specs.FRONTS,
        "side_effect_free_health": True,
        "suggested_port": port,
        "endpoints": [dict(e, tools=list(e["tools"])) for e in specs.ENDPOINTS],
        "tool_count": len(specs.tool_names()),
        "tools": [t["name"] for t in tool_list()],
        "port_owners": specs.port_owners(),
        "runtime": {"state_dir": STATE_DIR, "log": LOG_FILE},
    }
    if probe:
        data["status"] = status(port, host)
    return data


def launch(workspace=None, port=3092, host="127.0.0.1", wait=8.0, python=None):
    """拉起（或复用）MCP 服务，并返回**同一个请求的探活回执**。

    返回 `{ok, reused, started, url, port, front_endpoints, tools, health, reason?}`。
    `ok=false` 只在真的起不来时出现，不假装成功。
    """
    alive, health = _health(port, host)
    if alive:
        return {
            "ok": True, "reused": True, "started": False,
            "url": f"http://{host}:{port}", "port": port,
            "front_endpoints": _fronts(host, port),
            "tools": health.get("tool_count"), "health": health,
        }

    if _port_taken(port, host):
        return {"ok": False, "reused": False, "started": False,
                "reason": "port_in_use_by_other_process", "port": port,
                "hint": "该端口被别的进程占用（端口只做建议，可换 --port 起在空闲端口）"}

    workspace = workspace or REPO_ROOT
    os.makedirs(STATE_DIR, exist_ok=True)
    py = python or sys.executable
    cmd = [py, "-m", "mcp_hub.cli", "serve", "--port", str(port), "--host", host]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [workspace, _LOCAL_AGENT_DIR] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    log = open(LOG_FILE, "ab")
    proc = subprocess.Popen(cmd, cwd=_LOCAL_AGENT_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
    except OSError:
        pass

    deadline = time.time() + wait
    while time.time() < deadline:
        alive, health = _health(port, host)
        if alive:
            return {
                "ok": True, "reused": False, "started": True, "pid": proc.pid,
                "url": f"http://{host}:{port}", "port": port,
                "front_endpoints": _fronts(host, port),
                "tools": health.get("tool_count"), "health": health,
                "log": LOG_FILE,
            }
        if proc.poll() is not None:
            break
        time.sleep(0.2)

    return {"ok": False, "reused": False, "started": False,
            "reason": "start_failed", "port": port, "pid": proc.pid,
            "hint": f"子进程已退出或探活超时，看日志：{LOG_FILE}"}


def _fronts(host, port):
    return {
        "http": f"http://{host}:{port}/message",
        "sse": f"http://{host}:{port}/sse",
        "jsonrpc": f"http://{host}:{port}/jsonrpc",
        "health": f"http://{host}:{port}/health",
    }
