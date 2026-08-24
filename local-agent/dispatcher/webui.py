# -*- coding: utf-8 -*-
"""
调度中枢 · Web 可视化面板（webui）
====================================
用户拍板 #5：**Web 可视化优先**。用 Python 标准库 `http.server` 起一个轻量
本地 Web 服务（零前端/依赖栈，可被 CI/本地一键起），渲染实时俯瞰视图：

  - 事件流：dispatch 全链路记录（事件→规则→目标→状态→守卫拦截原因）；
  - 待路由队列：queued / hold（人工审核闸门）待处理项；
  - 已派发：dispatched 记录与目标 agent；
  - 守卫拦截：rejected / skipped 记录（人类看"拦了多少无效"）；
  - 驳回闭环：rejections 表（迭代次数/状态/负责 agent，驳回非终点）；
  - 哨兵监控：sentinel_actions（进度上限/停滞/横跳/重复错误）断点；
  - 队列/驳回统计摘要。

起服务：
  python -m local-agent.dispatcher.webui --port 8080
"""
import html
import json
import sys
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import db, schema
from dispatcher import queue as queue_mod
from dispatcher import reject as reject_mod


def _overview_payload():
    """聚合面板所需全部二级信息（事件流/队列/驳回/哨兵/统计）。"""
    schema.init_schema()
    dispatch_rows = db.query("SELECT * FROM dispatch ORDER BY id DESC LIMIT 200")
    queue_rows = queue_mod.queued(limit=200)
    hold_rows = queue_mod.hold_entries(limit=200)
    rejects = reject_mod.all_rejections(limit=200)
    sentinel_rows = db.query(
        "SELECT * FROM sentinel_actions ORDER BY id DESC LIMIT 100"
    )
    meters = db.query("SELECT * FROM goal_meters ORDER BY id DESC LIMIT 100")
    return {
        "dispatch": [dict(r) for r in dispatch_rows],
        "queue": queue_rows,
        "hold": hold_rows,
        "rejections": rejects,
        "sentinel_actions": [dict(r) for r in sentinel_rows],
        "goal_meters": [dict(r) for r in meters],
        "queue_overview": queue_mod.overview(),
        "rejection_overview": reject_mod.overview(),
        "now": datetime.utcnow().isoformat(),
    }


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>架构师 Agent · 调度中枢监控面板</title>
<style>
body{font-family:Menlo,Consolas,monospace;margin:0;padding:20px;background:#0f1419;color:#d0d8e0;}
h1{color:#4fc3f7;font-size:20px;} h2{color:#81c784;font-size:15px;border-bottom:1px solid #333;padding-bottom:4px;}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:6px;}
.st{queued:#ffb300}.st{released:#42a5f5}.st{dispatched:#66bb6a}.st{hold:#ef5350}
.st{rejected:#ab47bc}.st{skipped:#78909c}
table{border-collapse:collapse;width:100%;margin-bottom:10px;font-size:12px;}
th,td{border:1px solid #2a2f3a;padding:4px 8px;text-align:left;}
th{background:#1a2029;color:#9ab;}
tr:nth-child(even){background:#151a22;}
.green{color:#66bb6a;} .red{color:#ef5350;} .yellow{color:#ffb300;} .dim{color:#78909c;}
.card{background:#151a22;border:1px solid #2a2f3a;border-radius:6px;padding:12px;margin-bottom:16px;}
.section{margin-bottom:26px;}
</style>
</head>
<body>
<h1>📡 架构师 Agent · 调度中枢监控面板</h1>
<div class="dim">更新于 {now}</div>

<div class="section card">
<h2>📊 队列 / 驳回统计</h2>
<table><tr><th>Action 队列状态</th><th>数量</th><th>驳回迭代状态</th><th>数量</th></tr>
<tr>
<td>{queue_stat_cells}</td><td>{queue_stat_vals}</td><td>{reject_stat_cells}</td><td>{reject_stat_vals}</td>
</tr></table>
</div>

<div class="section card">
<h2>⏳ 待路由队列（queued / 人工审核闸门 hold）</h2>
<p class="dim">gate=hold 需人工判断放行；其余 auto 自动派发，不卡进程。</p>
{table_queue}
</div>

<div class="section card">
<h2>🔄 驳回迭代闭环（驳回非终点，按 gid 回派改进重提）</h2>
{table_reject}
</div>

<div class="section card">
<h2>🛡️ 守卫拦截 / 已派发 / 事件流（dispatch 全链路）</h2>
{table_dispatch}
</div>

<div class="section card">
<h2>⛔ 哨兵断点（进度上限/停滞/横跳/重复错误）</h2>
{table_sentinel}
</div>

<div class="section card">
<h2>📏 目标进度尺（量化距离 / 最大完成度）</h2>
{table_meters}
</div>

</body></html>
"""


def _badge(status):
    return f'<span class="badge st">{html.escape(str(status))}</span>'


def _render_table(headers, rows, rowmap=None):
    if not rows:
        return '<p class="dim">（空）</p>'
    thead = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        if rowmap:
            cells = rowmap(r)
        elif isinstance(r, dict):
            cells = [r.get(h, "") for h in headers]
        else:
            cells = r  # 已是 list 行
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
    return f"<table><tr>{thead}</tr>{body}</table>"


def render_html(payload):
    q = payload
    # 队列表
    q_rows = []
    for r in q["queue"]:
        q_rows.append([_badge(r["status"]), r["event_type"], r["entity"],
                       r.get("matched_rule", ""), r.get("target_role", ""),
                       _badge(r["gate"]), r.get("note", "")])
    t_queue = _render_table(
        ["状态", "事件类型", "实体", "命中规则", "目标角色", "闸门", "说明"], q_rows)

    # 驳回表
    r_rows = []
    for r in q["rejections"]:
        r_rows.append([_badge(r["status"]), r["task_id"], r["gid"], r["agent_id"],
                       r["iteration"], r["level"], r["reason"]])
    t_reject = _render_table(
        ["状态", "任务 gid", "实体 gid", "负责 agent", "迭代次数", "级别", "驳回原因"], r_rows)

    # dispatch 全链路
    d_rows = []
    for r in q["dispatch"]:
        d_rows.append([_badge(r["status"]), r["event_type"], r["entity"],
                       r.get("matched_rule", ""), r.get("target_agent", ""),
                       r.get("gate", ""), r.get("note", "")])
    t_dispatch = _render_table(
        ["状态", "事件", "实体", "命中规则", "目标 agent", "闸门", "说明"], d_rows)

    # 哨兵断点
    s_rows = []
    for r in q["sentinel_actions"]:
        detail = r.get("detail", "")
        try:
            detail = json.loads(detail).get("note", detail)
        except Exception:
            pass
        s_rows.append([_badge(f"L{r['level']}"), r["reason"], r["task_id"],
                       r.get("agent_id", ""), detail])
    t_sentinel = _render_table(["级别", "原因", "任务", "agent", "详情"], s_rows)

    # 目标进度尺
    m_rows = []
    for r in q["goal_meters"]:
        ratio = (r["current"] / r["goal_total"]) if r.get("goal_total") else 0
        m_rows.append([r["task_id"], r.get("agent_id", ""),
                       f"{round(r['current'],3)}/{round(r['goal_total'],3)}",
                       f"{round(ratio*100,1)}%", r.get("note", "")])
    t_meters = _render_table(["任务", "agent", "已达/目标", "完成度", "说明"], m_rows)

    qo = q["queue_overview"]
    ro = q["rejection_overview"]
    q_keys = "".join(f"<td>{_badge(k)}</td>" for k in qo)
    q_vals = "".join(f"<td>{v}</td>" for v in qo.values())
    r_keys = "".join(f"<td>{_badge(k)}</td>" for k in ro)
    r_vals = "".join(f"<td>{v}</td>" for v in ro.values())

    return (_HTML_TEMPLATE
            .replace("{now}", q["now"])
            .replace("{table_queue}", t_queue)
            .replace("{table_reject}", t_reject)
            .replace("{table_dispatch}", t_dispatch)
            .replace("{table_sentinel}", t_sentinel)
            .replace("{table_meters}", t_meters)
            .replace("{queue_stat_cells}", q_keys or "<td>-</td>")
            .replace("{queue_stat_vals}", q_vals or "<td>-</td>")
            .replace("{reject_stat_cells}", r_keys or "<td>-</td>")
            .replace("{reject_stat_vals}", r_vals or "<td>-</td>"))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = _overview_payload()
            page = render_html(payload)
        except Exception as e:  # noqa
            page = f"<pre>面板生成失败: {html.escape(str(e))}</pre>"
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # 人工审核闸门放行：POST /release/<event_id>
        path = self.path
        if path.startswith("/release/"):
            event_id = path.split("/")[-1]
            queue_mod.human_release(event_id)
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"method not supported"
        self.send_response(405)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 抑制默认日志
        pass


def serve(port=8080):
    schema.init_schema()
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"调度中枢 Web 面板运行于 http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n面板已停止")
        server.server_close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="调度中枢 Web 面板")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
