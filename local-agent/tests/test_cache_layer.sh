#!/usr/bin/env bash
# 全链路缓存层 + 缓存命中监控 测试（信号灯）
# =============================================================
# 验证用户 Issue #41 全链路缓存优化（CP1 已确认）+ 缓存命中监控要求：
#   M1 LLM 层 context caching + generate() 别名修复
#   M2 角色壳层共享前缀抽取
#   M3 编排层跨节点前缀复用
#   M4 末端 prefix_cache 接入上游共享前缀
#   M5 数据层 cache_stats 表
#   M6 缓存命中监控机制（按 agent 量化效果/浪费判定，本测试重点）
set -e
cd "$(dirname "$0")/.."

pass=0; fail=0
t() {
  local desc="$1"; shift
  if eval "$*" >/tmp/cache_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/cache_out.txt; fail=$((fail+1))
  fi
}

echo "==== 全链路缓存层 + 缓存命中监控 测试 ===="

# ---- M1 LLM 层：generate() 别名修复 + context caching 透传 ----
t "M1 llm.generate() 别名修复（原断裂 bug）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from llm import get_backend
b=get_backend()
assert hasattr(b,"generate"), "generate() 缺失"
r=b.generate("测试输入", system_prompt="你是架构·开发。")
assert isinstance(r,str) and len(r)>0, "generate() 应返回非空"
# context caching 透传头
from llm import cache
hdrs=cache.build_cache_headers()
assert "ep_ctxcache" in str(hdrs), f"应透传 ctxcache 头: {hdrs}"
print("generate 修复 + ctxcache 透传 OK")
PY'

# ---- M2 角色壳层共享前缀抽取 ----
t "M2 shell_cache 抽取共享壳前缀 + 集群聚合" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from roles import DeveloperRole, ReviewerRole, TesterRole
from roles import shell_cache
roles=[DeveloperRole(), ReviewerRole(), TesterRole()]
common=shell_cache.shared_shell_prefix(roles)
assert "架构" in common, f"公共前缀应含架构: {common!r}"
# 单角色前缀抽取
sp, _ = shell_cache.extract_shared_prefix(DeveloperRole.SYSTEM_PROMPT)
assert "架构·开发" in sp, "应抽取出角色前缀"
clusters=shell_cache.cluster_roles(roles)
assert len(clusters)>=1, "应至少聚出集群"
# 缓存成本计算
for p,g in clusters:
    total,pc,hits,saved=shell_cache.cache_cost_for_cluster((p,g))
    assert total>0 and pc>=0
print(f"集群数={len(clusters)} 公共前缀长度={len(common)}")
PY'

# ---- M3 编排层跨节点前缀复用 ----
t "M3 编排层跨节点缓存事件记录" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from llm import cache as _cache
# 模拟编排层调用 _run_one 的缓存记录
_cache.record_cache_event("架构·开发","orchestrator",1,24,8)
rows=_cache.cache_hit_rate_for(agent="架构·开发", layer="orchestrator")
assert rows and rows[0]["hits"]>=1, "编排层缓存事件应记录"
print(f"编排层缓存事件: {rows}")
PY'

# ---- M4 末端 prefix_cache 接入上游共享前缀 ----
t "M4 prefix_cache 接入上游共享前缀（extend_shared_prefix）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import prefix_cache
base="你是架构·开发。需求: 登录系统。"
upstream="你是「架构·"
ext=prefix_cache.extend_shared_prefix(base, upstream)
assert upstream in ext, "应叠加上游前缀"
# 去重：上游已在末端则不重复
ext2=prefix_cache.extend_shared_prefix(base, base)
assert ext2==base, "已包含时不应重复拼接"
an=prefix_cache.analyze_with_upstream([{"id":"a","role":"架构·开发","action":"A"}], "需求", upstream)
assert an["extended"]==True and an["upstream_prefix_chars"]>0
print(f"上游接入OK: 叠加={len(ext)}字符")
PY'

# ---- M5 数据层 cache_stats 表 ----
t "M5 数据层 cache_stats 表初始化 + 读写" bash -c '
  python3 - <<PY
import sys, os
os.environ["DB_PATH"]="/tmp/test_cache_layer.db"
if os.path.exists("/tmp/test_cache_layer.db"): os.remove("/tmp/test_cache_layer.db")
sys.path.insert(0,"local-agent")
from data import schema, db
tables=schema.init_schema()
assert "cache_stats" in tables, "应建 cache_stats 表"
db.execute("INSERT INTO cache_stats (agent,layer,cache_hits,cache_misses,cache_hit_rate,prefix_chars,saved_tokens) VALUES (?,?,?,?,?,?,?)",
           ("架构·测试","node",4,1,80,400,133))
rows=db.query("SELECT * FROM cache_stats")
assert len(rows)==1 and rows[0]["cache_hit_rate"]==80
print("cache_stats 表读写 OK")
PY'

# ---- M6 缓存命中监控机制（按 agent 量化效果/浪费判定）· 用户核心诉求 ----
t "M6 缓存命中监控：高命中=无浪费、低命中+重复构造=有浪费" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import cache_monitor
from llm import cache as _cache
# 高命中 agent → 无浪费
for _ in range(6):
    _cache.record_cache_event("架构·开发","node",1,300,100)
# 低命中 + 重复构造共享前缀 → 有浪费
for _ in range(4):
    _cache.record_cache_event("架构·评审","node",0,0,0)
_cache.record_cache_event("架构·评审","node",1,200,66)
r=cache_monitor.monitor()
assert r["overall_rate"] is not None
agents={s["agent"]:s for s in r["agents"]}
dev=agents["架构·开发"]
rev=agents["架构·评审"]
assert "无浪费" in dev["waste_verdict"], f"开发应无浪费: {dev[chr(119)+chr(97)+chr(115)+chr(116)+chr(101)+chr(95)+chr(118)+chr(101)+chr(114)+chr(100)+chr(105)+chr(99)+chr(116)]}"
assert "有浪费" in rev["waste_verdict"], f"评审应有浪费: {rev[chr(119)+chr(97)+chr(115)+chr(116)+chr(101)+chr(95)+chr(118)+chr(101)+chr(114)+chr(100)+chr(105)+chr(99)+chr(116)]}"
print(f"开发={dev[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(95)+chr(114)+chr(97)+chr(116)+chr(101)]}%({dev[chr(119)+chr(97)+chr(115)+chr(116)+chr(101)+chr(95)+chr(118)+chr(101)+chr(114)+chr(100)+chr(105)+chr(99)+chr(116)]}) 评审={rev[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(95)+chr(114)+chr(97)+chr(116)+chr(101)]}%({rev[chr(119)+chr(97)+chr(115)+chr(116)+chr(101)+chr(95)+chr(118)+chr(101)+chr(114)+chr(100)+chr(105)+chr(99)+chr(116)]})")
PY'

# ---- M6b 缓存监控持久化到 cache_stats ----
t "M6b 缓存命中监控持久化到数据层" bash -c '
  python3 - <<PY
import sys, os
os.environ["DB_PATH"]="/tmp/test_cache_layer_persist.db"
if os.path.exists("/tmp/test_cache_layer_persist.db"): os.remove("/tmp/test_cache_layer_persist.db")
sys.path.insert(0,"local-agent")
from data import schema, db
schema.init_schema()
from topology import cache_monitor
from llm import cache as _cache
_cache.record_cache_event("架构·开发","shell",1,0,0)
_cache.record_cache_event("架构·开发","shell",1,500,166)
r=cache_monitor.monitor(persist=True)
assert r["persisted"]>=1, f"应持久化到 cache_stats: {r}"
rows=db.query("SELECT agent,layer FROM cache_stats")
assert any("架构·开发"==x["agent"] for x in rows)
print("缓存监控持久化 OK")
PY'

echo ""
echo "==== 结果: ${pass} 通过, ${fail} 失败 ===="
[ "$fail" -eq 0 ]
