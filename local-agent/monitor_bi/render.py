# -*- coding: utf-8 -*-
"""
monitor_bi · 可视化渲染（M5 · render.py）
==========================================
把 M1-M4 聚合结果渲染为 **Markdown BI 大屏**（人类俯瞰二级信息视图）。

输出 `docs/BI_DASHBOARD.md`，风格与现有 DASHBOARD.md 统一（Markdown 表格 + 摘要）。
含：四维汇总表 + token 趋势 + 代码变化表 + 异常清单（⚠️ 标注）+ 刷新指南。
"""
import datetime
import os

from monitor_bi import stats, token, code, anomaly


def render(header="工作过程监控 · BI 大屏"):
    """生成 BI 大屏 Markdown 文本。"""
    now = datetime.datetime.utcnow().isoformat()
    lines = []

    # 标题 + 元信息
    lines.append(f"# 📊 {header}")
    lines.append("")
    lines.append(f"> 由 `monitor_bi` 自动生成 · 刷新时间 {now}")
    lines.append("")
    lines.append("> 数据源：data 层各表（agents/messages/tasks/progress/archives/stats/")
    lines.append("token_usage/code_changes）+ sentinel 异常引擎。")
    lines.append("")
    lines.append("## 一、体系概览")
    lines.append("")

    # ---- 一、概览 ----
    try:
        agents = _count("agents")
        messages = _count("messages")
        tasks = _count("tasks")
        archives = _count("archives")
        token_total = token.token_summary()["total"]
        code_t = code.code_total()
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 活跃 Agent | {agents} |")
        lines.append(f"| 消息总数 | {messages} |")
        lines.append(f"| 任务总数 | {tasks} |")
        lines.append(f"| 产出存档 | {archives} |")
        lines.append(f"| Token 总消耗 | {token_total:,} |")
        lines.append(f"| 代码新增 | +{code_t['added']:,} 行 |")
        lines.append(f"| 代码删除 | -{code_t['deleted']:,} 行 |")
        lines.append("")
    except Exception as e:
        lines.append(f"> ⚠️ 概览统计失败: {e}")
        lines.append("")

    # ---- 二、四维统计 ----
    lines.append("## 二、四维统计口径")
    lines.append("")
    for dim, label in [("agent", "Agent"), ("role", "岗位"), ("conversation", "对话"), ("project", "项目")]:
        try:
            rows = stats.workload_4d(dim)
            lines.append(f"### {label} 维度")
            lines.append("")
            if not rows:
                lines.append("_暂无数据_")
            else:
                lines.append(f"| {label} | 进度事件 | 消息数 | 产出数 | 总工作量 |")
                lines.append(f"|--------|----------|--------|--------|----------|")
                for r in rows[:10]:
                    lines.append(f"| {r['key']} | {r['progress_count']} | {r['message_count']} | {r['archive_count']} | {r['total']} |")
            lines.append("")
        except Exception as e:
            lines.append(f"> ⚠️ {label} 维度统计失败: {e}")
            lines.append("")

    # ---- 三、Token 消耗趋势 ----
    lines.append("## 三、Token 消耗")
    lines.append("")
    try:
        tk = token.token_summary("agent", trend=True)
        lines.append(f"**总消耗**: {tk['total']:,} tokens")
        lines.append("")
        if tk.get("trend"):
            lines.append("### 趋势（按小时）")
            lines.append("")
            lines.append(f"| 时间 | Token |")
            lines.append(f"|------|-------|")
            for t in tk["trend"][-20:]:
                lines.append(f"| {t['bucket']} | {t['tokens']:,} |")
            lines.append("")
    except Exception as e:
        lines.append(f"> ⚠️ Token 统计失败: {e}")
        lines.append("")

    # ---- 四、代码变化 ----
    lines.append("## 四、代码变化")
    lines.append("")
    try:
        by_project = code.code_by_project()
        lines.append("### 按项目")
        lines.append("")
        if not by_project:
            lines.append("_暂无数据_")
        else:
            lines.append(f"| 项目 | 新增 | 删除 | 净变化 | 提交数 |")
            lines.append(f"|------|------|------|--------|--------|")
            for r in by_project[:10]:
                lines.append(f"| {r['key']} | +{r['added']} | -{r['deleted']} | {r['net']:+d} | {r['commits']} |")
        lines.append("")
    except Exception as e:
        lines.append(f"> ⚠️ 代码变化统计失败: {e}")
        lines.append("")

    # ---- 五、异常监控 ----
    lines.append("## 五、异常监控")
    lines.append("")
    try:
        anoms = anomaly.anomaly_scan()
        if not anoms:
            lines.append("✅ 未检测到异常")
        else:
            lines.append(f"⚠️ 发现 **{len(anoms)}** 项异常：")
            lines.append("")
            lines.append(f"| 实体 | 类型 | 原因 | 严重级 |")
            lines.append(f"|------|------|------|--------|")
            for a in anoms:
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a.get("severity", "low"), "🟢")
                lines.append(f"| {a['entity']} | {a['type']} | {a['reason']} | {sev_icon} {a['severity']} |")
        lines.append("")
    except Exception as e:
        lines.append(f"> ⚠️ 异常扫描失败: {e}")
        lines.append("")

    # ---- 六、刷新指南 ----
    lines.append("## 六、刷新指南")
    lines.append("")
    lines.append("```bash")
    lines.append("# 实时查询（终端输出）")
    lines.append("python -m monitor_bi.cli overview")
    lines.append("")
    lines.append("# 生成 BI 大屏文档")
    lines.append("python -m monitor_bi.cli render")
    lines.append("```")

    return "\n".join(lines)


def render_to_file(path=None):
    """渲染并写入 Markdown 文件（默认 docs/BI_DASHBOARD.md）。"""
    if path is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(repo_root, "docs", "BI_DASHBOARD.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = render()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _q(sql):
    from data import db
    rows = db.query(sql)
    return [dict(r) for r in rows]


def _count(table):
    """统计表行数（正确取聚合值）。"""
    rows = _q(f"SELECT COUNT(*) AS n FROM {table}")
    return rows[0]["n"] if rows else 0
