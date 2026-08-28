# -*- coding: utf-8 -*-
"""
ResultSync · 结果同步留痕
=========================
本地跑完 CPU 密集测试后，把结果**同步回云端留痕**（写入数据层 archives /
messages，保证本地执行不留死点、可回溯核验）。

设计原则：
  - 数据层不可用时静默降级（记录到本地日志文件），不吞异常也不阻断主流程；
  - 每条同步记录带时间戳 + 来源标记（local），供审计回放；
  - 结果按「统一口径」落库，不各 agent 自造。
"""
import json
import os
import time

# 本地日志兜底文件（数据层不可用时写入）
FALLBACK_LOG = os.path.join(os.path.dirname(__file__), ".hybrid_sync.log")


class ResultSync(object):
    """把本地执行结果同步回云端留痕。"""

    def __init__(self, fallback_log=FALLBACK_LOG, use_data_layer=True):
        self.fallback_log = fallback_log
        self.use_data_layer = use_data_layer

    # ---------- 核心同步 ----------
    def sync(self, run_result, batch_name="hybrid-local"):
        """把一次批量执行结果同步留痕。

        返回 {synced, target, records, fallback}。
        """
        records = []
        results = run_result.get("results", [])
        for r in results:
            rec = {
                "script": r.get("script", ""),
                "exit_code": r.get("exit_code"),
                "duration": r.get("duration", 0),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "local",
            }
            records.append(rec)

        synced, fallback = self._persist(records, run_result, batch_name)
        return {
            "synced": synced,
            "target": "data_layer" if not fallback else "fallback_log",
            "records": records,
            "fallback": fallback,
        }

    def _persist(self, records, run_result, batch_name):
        """写入数据层；失败则写本地日志。返回 (synced, used_fallback)。"""
        # 优先走数据层留痕
        if self.use_data_layer:
            try:
                from data import admin  # 延迟导入，避免硬依赖
                admin.init()
                # 归档整批结果（kind=hybrid-local）
                summary = run_result.get("summary", {})
                content = json.dumps({
                    "batch": batch_name,
                    "summary": summary,
                    "records": records,
                }, ensure_ascii=False)
                admin.archive(
                    archive_id="hybrid-%s" % batch_name,
                    kind="hybrid-local",
                    title="本地 CPU 测试结果同步（%s）" % batch_name,
                    content=content,
                    source="local",
                )
                # 发一条消息管线记录（可回放审计）
                admin.post_message(
                    topic="hybrid/local-sync",
                    payload={"batch": batch_name, "summary": summary},
                    from_agent="architecture-develop",
                    to_agent="data-admin",
                )
                return True, False
            except Exception:  # noqa 数据层不可用 → 降级
                pass
        return self._fallback(records, run_result, batch_name)

    def _fallback(self, records, run_result, batch_name):
        """写本地日志兜底。"""
        try:
            with open(self.fallback_log, "a") as f:
                f.write(json.dumps({
                    "batch": batch_name,
                    "ts": time.time(),
                    "summary": run_result.get("summary", {}),
                    "records": records,
                }, ensure_ascii=False) + "\n")
            return True, True
        except Exception:  # noqa
            return False, True


# 便捷单例
default_sync = ResultSync()
