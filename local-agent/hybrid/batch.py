# -*- coding: utf-8 -*-
"""
CloudBatch · 云端批量打包提交器（防频繁唤醒）
================================================
问题：每次需求都单独提交云端 = 云端 CodeBuddy 频繁唤醒（每次唤醒有冷启动/
上下文重建成本，云端 CPU 计费高）。CPU 密集活已由 LocalWorker 本地消化，
剩给云端的 LLM 强相关任务应【攒批】成一批，一次唤醒处理多个任务。

本模块提供：
  - enqueue(task)        任务入批（本地瞬时报达，0 成本）
  - flush(dry)           攒够一批后一次提交云端（新建 Task Issue，携带
                         协议化任务声明；默认 1 Issue 打包多任务）
  - status()             查看攒批队列

复用协议：
  - 任务声明协议（yunduanjiaohu/protocol/任务声明协议.md）：Issue body
    内嵌 yaml 结构化任务元数据，云端 CodeBuddy 自动解析。
  - 秘钥：环境变量 cnbcooldong（CNB 访问令牌）；可用 CNB_REPO 覆盖目标仓库。
"""
import json
import os
import time

# 默认目标仓库（本地 ⇄ 云端协议仓库）
DEFAULT_REPO = os.environ.get("CNB_REPO", "dongdongxiaozu/yunduanjiaohu")
API_BASE = os.environ.get("CNB_API", "https://api.cnb.cool")

# 攒批队列文件（与 CLI 的 .last_run.json 同习惯，放模块目录）
QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".batch_queue.json")

# 攒批阈值可调
DEFAULT_MIN_TASKS = 3        # 攒够 3 个任务才值得唤醒一次云端
DEFAULT_MAX_WAIT_SECONDS = 3600  # 最多等 1 小时（时间窗兜底）


class CloudBatch(object):
    """云端批量打包器：本地攒批（0 成本），一次提交（一次唤醒）。"""

    def __init__(self, repo=DEFAULT_REPO, min_tasks=DEFAULT_MIN_TASKS,
                 max_wait=DEFAULT_MAX_WAIT_SECONDS, queue_file=QUEUE_FILE):
        self.repo = repo
        self.min_tasks = min_tasks
        self.max_wait = max_wait
        self.queue_file = queue_file

    # ---------- 队列存取 ----------
    def _load(self):
        try:
            if os.path.exists(self.queue_file):
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "tasks" in data:
                        return data
        except Exception:  # noqa
            pass
        return {"tasks": [], "created_at": time.time()}

    def _save(self, data):
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---------- 入批 ----------
    def enqueue(self, title, description="", project="", location="",
                priority="P2 中", acceptance=None, meta=None):
        """一个任务入批。title 必填；其余按任务声明协议字段。

        入批是纯本地操作（零成本），绝不直接唤醒云端。
        """
        data = self._load()
        data["tasks"].append({
            "title": title,
            "description": description,
            "project": project,
            "location": location,
            "priority": priority,
            "acceptance": acceptance or [],
            "meta": meta or {},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        data.setdefault("created_at", time.time())
        self._save(data)
        return {"queued": len(data["tasks"]), "min_tasks": self.min_tasks,
                "ready": self.ready()}

    # ---------- 判定 ----------
    def ready(self):
        """攒够最小任务数 = 值得唤醒一次云端。"""
        data = self._load()
        return len(data["tasks"]) >= self.min_tasks

    def status(self):
        data = self._load()
        n = len(data["tasks"])
        age = time.time() - data.get("created_at", time.time()) if n else 0
        return {
            "queued": n,
            "min_tasks": self.min_tasks,
            "ready": self.ready(),
            "max_wait_seconds": self.max_wait,
            "age_seconds": int(age),
            "time_window_ready": age >= self.max_wait if n else False,
            "tasks": [t["title"] for t in data["tasks"]],
        }

    # ---------- 打包 ----------
    def _build_issue_body(self, tasks):
        """按任务声明协议生成打包 Issue body：一个 Issue 内嵌多任务声明。"""
        lines = [
            "# 批量任务承接单（CloudBatch 打包）",
            "",
            "> 本 Issue 由本地 CloudBatch 批量打包提交，包含 %d 个任务。" % len(tasks),
            "> 云端 CodeBuddy 一次唤醒，按序承接全部任务，成果按回传协议统一回传本 Issue。",
            "",
        ]
        for i, t in enumerate(tasks, 1):
            lines.append("## 任务 %d：%s" % (i, t["title"]))
            lines.append("")
            lines.append("```yaml")
            lines.append("task%d:" % i)
            lines.append('  title: "%s"' % t["title"])
            if t.get("project"):
                lines.append('  project: "%s"' % t["project"])
            if t.get("location"):
                lines.append('  location: "%s"' % t["location"])
            lines.append('  priority: "%s"' % (t.get("priority") or "P2 中"))
            lines.append("  acceptance:")
            for a in (t.get("acceptance") or []):
                lines.append('    - "%s"' % a)
            lines.append("```")
            if t.get("description"):
                lines.append("")
                lines.append(t["description"])
            lines.append("")
        lines.append("---")
        lines.append("## 批量承接约定")
        lines.append("- 每个任务完成后按【成果回传协议】在评论回传（状态/成果清单/验收核对）")
        lines.append("- 全部完成或部分阻塞时，汇总回复一次即可")
        return "\n".join(lines)

    def flush(self, dry_run=False, post_comment=False):
        """把攒批队列一次提交云端。

        dry_run=True：只生成 Issue 内容不真正创建（CI 演练/审计）。
        post_comment=True：提交后再补一条 @CodeBuddy 评论触发唤醒（可选，
        默认只建 Issue，云端按仓库规则自动承接；避免过度唤醒）。
        """
        data = self._load()
        tasks = data.get("tasks", [])
        if not tasks:
            return {"submitted": 0, "reason": "empty queue"}
        n = len(tasks)
        title = "[批量] %s 等 %d 个任务（CloudBatch）" % (tasks[0]["title"][:30], n)
        body = self._build_issue_body(tasks)

        if dry_run:
            self._save({"tasks": [], "created_at": time.time()})
            return {
                "submitted": n, "dry_run": True,
                "title": title, "body_preview": body[:600],
                "repo": self.repo,
            }

        result = self._create_issue(title, body)
        if result.get("number"):
            # 提交成功清空队列（失败保留，等待下次 flush）
            self._save({"tasks": [], "created_at": time.time()})
            if post_comment:
                self._post_comment(result["number"], "@CodeBuddy 请按本批量任务单承接处理。")
                result["comment_posted"] = True
        return result

    # ---------- CNB API ----------
    def _host_env(self, name):
        """在 WSL 里读 Windows 宿主环境变量（WSL 默认不继承 Windows env）。"""
        try:
            import subprocess as sp
            out = sp.run(["cmd.exe", "/c", "echo %%%s%%" % name],
                         capture_output=True, text=True, timeout=10)
            v = (out.stdout or "").strip().strip("\r")
            return v if v and "%" not in v else None
        except Exception:  # noqa
            return None

    def _headers(self):
        token = (os.environ.get("cnbcooldong") or os.environ.get("CNB_TOKEN")
                 or self._host_env("cnbcooldong") or self._host_env("CNB_TOKEN"))
        if not token:
            raise RuntimeError("缺少 cnbcooldong/CNB_TOKEN 环境变量（CNB 访问令牌）")
        return {
            "Authorization": "Bearer %s" % token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _create_issue(self, title, body):
        # 唯一标题契约闸门（Issue #343）：批量提交也不许自由文本当标题。
        # 走 `expertise.issue_source` 读**真实存量**（不是传空清单）——传空等于告诉
        # 闸门「仓库里没有任何 Issue」，reuse 分支永远进不去，去重形同虚设。
        gated = None
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from expertise import issue_contract as _ic
            from expertise import issue_source as _src
            snap = _src.existing(self.repo)
            gated = _ic.guard_create(title, snap.get("items") or [],
                                     module="local-agent", issue_type="CHORE", seed=title)
        except Exception:  # noqa: BLE001  契约不可用不阻断，显式降级（不假装守约）
            gated = None
        if gated is not None:
            action = gated.get("action")
            if action == "reject":
                # 无法契约化 → 中止提交，绝不静默回落垃圾原标题
                return {"error": "标题无法契约化，已中止提交：" + str(gated.get("reason") or ""),
                        "gate": gated}
            if action == "reuse":
                return {"number": gated.get("reuse_number"), "reused": True,
                        "title": gated.get("title"), "gate": gated,
                        "url": "%s/%s/-/issues/%s" % (API_BASE, self.repo,
                                                      gated.get("reuse_number"))}
            title = gated.get("title") or title
        url = "%s/%s/-/issues" % (API_BASE, self.repo)
        payload = json.dumps({"title": title, "body": body}, ensure_ascii=False)
        import urllib.request
        req = urllib.request.Request(url, data=payload.encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                try:      # 回填存量：同批后续提交也能去重
                    from expertise import issue_source as _src
                    _src.remember(self.repo, data.get("number"), data.get("title"))
                except Exception:  # noqa: BLE001
                    pass
                return {"number": data.get("number"), "state": data.get("state"),
                        "title": data.get("title"), "url": "%s/%s/-/issues/%s" % (API_BASE, self.repo, data.get("number"))}
        except Exception as e:  # noqa
            return {"error": str(e)[:300]}

    def _post_comment(self, number, text):
        url = "%s/%s/-/issues/%s/comments" % (API_BASE, self.repo, number)
        payload = json.dumps({"body": text}, ensure_ascii=False)
        import urllib.request
        req = urllib.request.Request(url, data=payload.encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status
        except Exception:  # noqa
            return None


# 便捷单例
default_batch = CloudBatch()
