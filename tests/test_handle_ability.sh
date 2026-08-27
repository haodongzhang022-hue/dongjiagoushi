#!/usr/bin/env bash
# ============================================================
# 自适应 @ 定位能力（HandleAbility）· 可复现功能测试（Issue #33）
# 仓库：dongjiagoushi
#
# 作用：把「跨库 @ 谁、@ 哪个仓库的谁」从写死的字符串升级为**根据触发仓库
#   自动解析**的机制，并用机器断言锁死，防止回退到写死角色名的写法。
#
# 覆盖用户诉求（Issue #33）：
#   T-H1 不写死角色名        —— 从触发串动态识别自身 CodeBuddy 角色承载仓库
#   T-H2 跨库用目标仓库 @     —— 跨仓库协作用目标仓库完整 @，权限更高
#   T-H3 同仓复用防冗余       —— 同仓库协作可复用本仓库 @，不重造
#   T-H4 解析器各格式支持     —— @org/repo(角色) / @org/repo / @repo / @CodeBuddy
#   T-H5 BaseRole 全员挂载    —— 每个角色实例都具备 self_handle / resolve / is_cross
#   T-H6 权限建议             —— 跨库/同库给出权限建议，避免选错角色受限
#   T-H7 CNB 环境变量识别      —— CNB_GROUP_SLUG/CNB_REPO_NAME/CNB_ROOT_SLUG/CNB_ORG 识别当前仓库（自适应 org）
#
# 用法：
#   bash tests/test_handle_ability.sh      # 本地运行
#   可在 .cnb.yml 的 test 阶段一并调用
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

# ------------------------------------------------------------
# 断言工具
# ------------------------------------------------------------
assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 缺少: $needle")
    echo "  ❌ $name  (实际: $haystack)"
  fi
}
assert_eq() {
  local name="$1" actual="$2" expect="$3"
  if [[ "$actual" == "$expect" ]]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 期望=$expect 实际=$actual")
    echo "  ❌ $name  (期望=$expect 实际=$actual)"
  fi
}

echo "======================================================"
echo "自适应 @ 定位能力（HandleAbility）· 可复现测试"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# 断言模块文件存在
assert_contains "T-H 模块 handle/__init__.py 存在" "$(ls local-agent/handle/__init__.py 2>/dev/null || echo MISSING)" "__init__"
assert_contains "T-H 模块 handle/resolver.py 存在" "$(ls local-agent/handle/resolver.py 2>/dev/null || echo MISSING)" "resolver"
assert_contains "T-H 模块 handle/ability.py 存在" "$(ls local-agent/handle/ability.py 2>/dev/null || echo MISSING)" "ability"
assert_contains "T-H BaseRole 挂载 handle_ability" "$(cat local-agent/roles/base.py)" "handle_ability"
assert_contains "T-H BaseRole 透传 self_handle" "$(cat local-agent/roles/base.py)" "def self_handle"
assert_contains "T-H BaseRole 透传 resolve" "$(cat local-agent/roles/base.py)" "def resolve"

# ------------------------------------------------------------
# 用 python 跑解析逻辑并输出可断言的标记串
# ------------------------------------------------------------
OUT=$(cd "$REPO_ROOT" && PYTHONPATH=local-agent python3 - <<'PY'
import sys
sys.path.insert(0, "local-agent")
from handle import resolver
from roles.base import BaseRole

res = {}

# T-H1: 从触发串动态识别自身（不写死 youkaifaxilieagent，而是从触发串读）
r = resolver.resolve(at_str="@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)",
                     current_org="dongdongxiaozu", current_repo="dongjiagoushi")
res["H1_handle"] = r["handle"]
res["H1_trigger_repo"] = r["trigger"]["repo"]
res["H1_src"] = r["source"]

# T-H2: 跨库用目标仓库 @
r2 = resolver.resolve(at_str="@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)",
                      target_org="dongdongxiaozu", target_repo="someotherrepo",
                      current_org="dongdongxiaozu", current_repo="dongjiagoushi")
res["H2_handle"] = r2["handle"]
res["H2_cross"] = r2["cross_repo"]
res["H2_note"] = r2["permission_note"]

# T-H3: 同仓复用（当前操作仓库，无 target）
r3 = resolver.resolve(current_org="dongdongxiaozu", current_repo="dongjiagoushi")
res["H3_handle"] = r3["handle"]
res["H3_cross"] = r3["cross_repo"]

# T-H4: 各格式解析
res["H4_full"] = resolver.parse_at("@orga/repoa(某角色)")["role"]
res["H4_two"] = resolver.format_at("orgb", "repob", "CodeBuddy")
res["H4_single"] = resolver.parse_at("@onlyrepo")["repo"]

# T-H7: CNB 平台实际注入环境变量识别（CNB_GROUP_SLUG/CNB_REPO_NAME）
import os as _os
def _env_probe(env):
    old = {k: _os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v
    try:
        return resolver._env_org_repo()
    finally:
        for k, v in old.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v

# CNB 平台标准变量 → 应识别
_res7 = _env_probe({"CNB_GROUP_SLUG": "dongdongxiaozu",
                    "CNB_REPO_NAME": "dongjiagoushi",
                    "CNB_ROOT_SLUG": None, "CNB_ORG": None, "CNB_REPO": None})
res["H7_cnb"] = f"{_res7[0]}/{_res7[1]}" if _res7 else "NONE"

# CNB 根命名空间兜底 + repo → 应识别
_res8 = _env_probe({"CNB_GROUP_SLUG": None, "CNB_ROOT_SLUG": "rootorg",
                    "CNB_REPO_NAME": "myrepo",
                    "CNB_ORG": None, "CNB_REPO": None})
res["H7_root"] = f"{_res8[0]}/{_res8[1]}" if _res8 else "NONE"

# 通用别名 CNB_ORG/CNB_REPO → 应识别
_res9 = _env_probe({"CNB_GROUP_SLUG": None, "CNB_ROOT_SLUG": None,
                    "CNB_REPO_NAME": None,
                    "CNB_ORG": "o1", "CNB_REPO": "r1"})
res["H7_alias"] = f"{_res9[0]}/{_res9[1]}" if _res9 else "NONE"

# T-H5: BaseRole 全员挂载
class Dev(BaseRole):
    name = "架构·开发"
d = Dev(at_str="@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)",
        current_org="dongdongxiaozu", current_repo="dongjiagoushi")
res["H5_self"] = d.self_handle()
res["H5_resolve"] = d.resolve("dongdongxiaozu", "otherrepo")["handle"]
res["H5_cross_same"] = d.is_cross("dongdongxiaozu", "dongjiagoushi")
res["H5_cross_diff"] = d.is_cross("dongdongxiaozu", "otherrepo")
res["H5_cap"] = "handle_ability" in d.capability()

# T-H6: 权限建议
res["H6_cross_note"] = r2["permission_note"]
res["H6_same_note"] = r3["permission_note"]

for k, v in res.items():
    print(f"{k}={v}")
PY
)

declare -A MAP
while IFS='=' read -r key val; do
  [ -n "$key" ] && MAP["$key"]="$val"
done <<< "$OUT"

# 输出原始供排错
echo "  [raw] $OUT"
echo ""

echo "▶ T-H1 不写死角色名（从触发串动态识别自身承载仓库）"
assert_eq "H1 自身 handle" "${MAP[H1_handle]}" "@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)"
assert_eq "H1 触发承载仓库动态识别" "${MAP[H1_trigger_repo]}" "youkaifaxilieagent"
assert_eq "H1 来源=trigger" "${MAP[H1_src]}" "trigger"

echo "▶ T-H2 跨库用目标仓库完整 @（权限更高）"
assert_eq "H2 跨库 handle" "${MAP[H2_handle]}" "@dongdongxiaozu/someotherrepo(CodeBuddy)"
assert_eq "H2 跨库判定=true" "${MAP[H2_cross]}" "True"
assert_contains "H2 权限建议含跨仓库提示" "${MAP[H2_note]}" "跨仓库"

echo "▶ T-H3 同仓复用防冗余"
assert_eq "H3 同仓 handle" "${MAP[H3_handle]}" "@dongdongxiaozu/dongjiagoushi(CodeBuddy)"
assert_eq "H3 同仓判定=false" "${MAP[H3_cross]}" "False"

echo "▶ T-H4 解析器各格式支持"
assert_eq "H4 @org/repo(角色) 解析角色" "${MAP[H4_full]}" "某角色"
assert_eq "H4 format_at 生成格式" "${MAP[H4_two]}" "@orgb/repob(CodeBuddy)"
assert_eq "H4 @单仓库 解析 repo" "${MAP[H4_single]}" "onlyrepo"

echo "▶ T-H5 BaseRole 全员挂载"
assert_eq "H5 self_handle" "${MAP[H5_self]}" "@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)"
assert_eq "H5 resolve 跨库" "${MAP[H5_resolve]}" "@dongdongxiaozu/otherrepo(CodeBuddy)"
assert_eq "H5 is_cross 同仓" "${MAP[H5_cross_same]}" "False"
assert_eq "H5 is_cross 跨仓" "${MAP[H5_cross_diff]}" "True"
assert_eq "H5 capability 含 handle_ability" "${MAP[H5_cap]}" "True"

echo "▶ T-H6 权限建议"
assert_contains "H6 跨库建议(必须用目标仓库)" "${MAP[H6_cross_note]}" "必须用目标仓库"
assert_contains "H6 同仓建议(可复用)" "${MAP[H6_same_note]}" "可复用"

echo "▶ T-H7 CNB 平台环境变量识别（自适应仓库，不假设 org 固定）"
assert_eq "H7 CNB_GROUP_SLUG+CNB_REPO_NAME 识别" "${MAP[H7_cnb]}" "dongdongxiaozu/dongjiagoushi"
assert_eq "H7 CNB_ROOT_SLUG 兜底+CNB_REPO_NAME 识别" "${MAP[H7_root]}" "rootorg/myrepo"
assert_eq "H7 CNB_ORG+CNB_REPO 通用别名识别" "${MAP[H7_alias]}" "o1/r1"

echo ""
echo "======================================================"
echo "自适应 @ 定位能力测试汇总：PASS=$PASS FAIL=$FAIL"
if [ $FAIL -eq 0 ]; then
  echo "✅ 信号灯：🟢 通过（不写死角色名 / 跨库权限 / 同仓复用 全部达成）"
  exit 0
else
  echo "❌ 信号灯：🔴 失败"
  printf '  - %s\n' "${FAILED_ITEMS[@]}"
  exit 1
fi
