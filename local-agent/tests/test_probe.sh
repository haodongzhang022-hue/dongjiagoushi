#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 脉冲式信号探测器（probe）功能测试
# 对齐用户拍板：轮询不好，换脉冲式信号探测器——有条件就触发、路由到脚本、
# 不多处一直轮询（轮询会静默失败）。验证：
#   ① 探测器注册（触发条件 + 路由动作），稳定寻址；
#   ② fire_signal 有条件就触发：命中探测器才触发一次，未命中显式暴露 miss；
#   ③ 路由到脚本：action.type=script 时路由执行脚本；
#   ④ 不静默失败：脚本失败/条件错误显式写 firing 且 note 标 error；
#   ⑤ LocalHostAdapter.emit 事件到达即触发探测器（不靠 poll 轮询消费）。
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [probe] 1. 探测器注册（触发条件+路由动作 · 稳定寻址）====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import probe
# 注册两个探测器
pid1 = probe.register_probe("dev-dispatch", event_type="requirement", source="local_pc",
                            action={"type": "dispatch", "target_role": "架构·开发"})
pid2 = probe.register_probe("repo-script", event_type="comment", source="repo",
                            action={"type": "handler"})
# 二次注册同一 name 应取回同一 id（稳定寻址，不漂移）
pid1_again = probe.register_probe("dev-dispatch", event_type="requirement", source="local_pc",
                                  action={"type": "dispatch", "target_role": "架构·产品"})
assert pid1 == pid1_again, "同一探测器二次注册应取回同一 id（稳定寻址）"
# 俯视图
probes = {p["name"]: p for p in probe.list_probes()}
assert "dev-dispatch" in probes and "repo-script" in probes, "探测器应已注册"
print(f"  探测器 {len(probes)} 个，二次注册取回同一 id ✅ 稳定寻址")
print("  ✅ 探测器注册（触发条件+路由动作 · 稳定寻址）通过")
EOF

echo "===== [probe] 2. 有条件就触发：命中才触发一次，未命中显式暴露 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import probe
# 注册探测器（本进程内，独立于上一段）
probe.register_probe("dev-dispatch", event_type="requirement", source="local_pc",
                    action={"type": "dispatch", "target_role": "架构·开发"})
probe.register_probe("repo-script", event_type="comment", source="repo",
                    action={"type": "handler"})
# 命中：requirement + local_pc
r1 = probe.fire_signal({"event_type": "requirement", "source": "local_pc",
                        "entity": "新需求", "detail": {}})
assert r1["matched"] == 1 and r1["fired"] == 1, f"命中探测器应触发一次: {r1}"
assert r1["ok"] is True and r1["missed"] is False
# 未命中：source 是 repo，不匹配 dev-dispatch 的 local_pc；且无 comment 探测器（handler 类型未启用事件）
# 这里只匹配 repo-script（handler），但 event_type=issue.open 不匹配 comment → 应 miss
r2 = probe.fire_signal({"event_type": "issue.open", "source": "repo",
                        "entity": "待审核 issue", "detail": {}})
# repo-script 只命中 comment，issue.open 不命中任何探测器
assert r2["matched"] == 0 and r2["missed"] is True, f"未命中应显式暴露 miss: {r2}"
# 去重：同一信号 id 重复投递应被去重护栏拦截（不重复触发）
r3 = probe.fire_signal({"event_id": "ev-test-dedup", "event_type": "requirement",
                        "source": "local_pc", "entity": "x", "detail": {}})
r3b = probe.fire_signal({"event_id": "ev-test-dedup", "event_type": "requirement",
                         "source": "local_pc", "entity": "x", "detail": {}})
assert r3["fired"] == 1 and r3b["fired"] == 0, "同信号 id 去重后不应重复触发"
print(f"  命中触发 {r1['fired']} 次 | 未命中 miss={r2['missed']} | 去重后二次 fired={r3b['fired']}")
print("  ✅ 有条件就触发（命中才触发·未命中显式暴露·去重防无效）通过")
EOF

echo "===== [probe] 3. 路由到脚本（action.type=script）====="
$PY - <<'EOF'
import os
from data import schema
schema.init_schema()
from dispatcher import probe
# 写一个探测脚本
script = "scripts/_probe_test_echo.py"
os.makedirs("scripts", exist_ok=True)
with open(script, "w", encoding="utf-8") as f:
    f.write("import sys, json\npayload = json.loads(sys.stdin.read())\n"
            "print(f\"SCRIPT_RAN:{payload['signal'].get('entity')}\")\n")
probe.register_probe("echo-script", event_type="comment", source="repo",
                     action={"type": "script", "script": script})
r = probe.fire_signal({"event_type": "comment", "source": "repo",
                       "entity": "hello-world", "detail": {}})
assert r["fired"] == 1 and r["ok"] is True, f"脚本应成功路由执行: {r}"
assert "SCRIPT_RAN:hello-world" in r["results"][0]["note"], r["results"][0]["note"]
print(f"  脚本路由执行成功: {r['results'][0]['note']}")
os.remove(script)
print("  ✅ 路由到脚本通过")
EOF

echo "===== [probe] 4. 不静默失败：脚本失败显式写 firing 且 note 标 error ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import probe
# 不存在的脚本 → 显式失败留痕
probe.register_probe("bad-script", event_type="comment", source="repo",
                     action={"type": "script", "script": "scripts/_no_such_script.py"})
r = probe.fire_signal({"event_type": "comment", "source": "repo",
                       "entity": "x", "detail": {}})
# 命中 2 个（echo 已删、bad-script），其中 bad-script 失败 → ok=False
assert r["ok"] is False, "存在失败脚本时整体 ok 应为 False"
ov = probe.firing_overview()
assert ov["error"] >= 1, "失败触发应显式写 error 留痕（不静默）"
print(f"  失败触发留痕 error={ov['error']}（显式上报，不静默吞异常）")
print("  ✅ 不静默失败（显式留痕 error）通过")
EOF

echo "===== [probe] 5. LocalHostAdapter.emit 事件驱动（不靠 poll 轮询消费）====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import probe, sources
# 注册一个本地探测器
probe.register_probe("local-req", event_type="requirement", source="local_pc",
                     action={"type": "handler"})
# 建本地适配器，emit 直接触发探测器（事件到达即触发，不进入队列等 poll）
adapter = sources.LocalHostAdapter(name="local_pc")
report = adapter.emit({"event_type": "requirement", "entity": "本地需求",
                       "detail": {"note": "来自本地电脑"}})
assert report is not None and report["matched"] >= 1, "emit 应直接触发探测器"
# 不再需要 poll 消费：暂存队列应为空（事件驱动主路径）
assert len(adapter._local_store) == 0, "emit 走探测器，不应残留本地暂存队列"
print(f"  emit 直接触发探测器 matched={report['matched']}，无轮询消费")
print("  ✅ LocalHostAdapter.emit 事件驱动（不靠 poll 轮询消费）通过")
EOF

echo "===== [probe] 6. CLI 入口 ====="
$PY -m dispatcher.cli signal overview >/dev/null 2>&1 && echo "  ✅ dispatcher.cli signal overview 可运行"
$PY -m dispatcher.cli signal fire --type requirement --source local_pc --entity cli-test >/dev/null 2>&1 && echo "  ✅ dispatcher.cli signal fire 可运行"

echo ""
echo "✅ [probe] 全部测试通过"
