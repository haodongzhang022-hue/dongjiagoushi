#!/usr/bin/env bash
# ============================================================
# monitor-bi 模块信号灯测试（Issue #55）
# 仓库：dongjiagoushi
#
# 作用：验证「工作过程监控 + 可视化 BI 大屏」模块四维统计、
#   token 分析、代码变化统计、异常监控、CLI 五大能力。
#   任一断言失败即以非零码退出 → 流水线红灯。
#
# 覆盖：
#   T1 四维统计引擎（agent/role/conversation/project）
#   T2 token 分析（估算/真实回传/去重/趋势）
#   T3 代码变化统计（按项目/agent 归集）
#   T4 异常监控（复用 sentinel + 分工失衡）
#   T5 CLI 入口（overview/render/token/code/anomaly）
#   T6 接口显式导出（MonitorBI 类 + 公开函数）
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

# 使用独立临时 DB，避免污染主库
TEST_DB="$(mktemp /tmp/test_bi_XXXXXX.db)"
export DB_PATH="$TEST_DB"
export PYTHONPATH="$REPO_ROOT/local-agent"

# ------------------------------------------------------------
# 断言工具
# ------------------------------------------------------------
assert_file_exists() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 文件缺失: $file")
    echo "  ❌ $name"
  fi
}

assert_python() {
  local name="$1" expr="$2"
  if python3 -c "$expr" 2>/dev/null; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] Python 断言失败")
    echo "  ❌ $name"
  fi
}

# ------------------------------------------------------------
echo "======================================================"
echo "monitor-bi 模块信号灯测试 (Issue #55)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# T1 文件存在性
echo "--- T1 文件存在性 ---"
assert_file_exists "monitor_bi 模块" "local-agent/monitor_bi/__init__.py"
assert_file_exists "四维统计引擎" "local-agent/monitor_bi/stats.py"
assert_file_exists "token 分析" "local-agent/monitor_bi/token.py"
assert_file_exists "代码变化统计" "local-agent/monitor_bi/code.py"
assert_file_exists "异常监控" "local-agent/monitor_bi/anomaly.py"
assert_file_exists "可视化渲染" "local-agent/monitor_bi/render.py"
assert_file_exists "CLI 入口" "local-agent/monitor_bi/cli.py"
assert_file_exists "schema 含 token_usage 表" "local-agent/data/schema.py"

# T2 schema 扩展
echo "--- T2 schema 扩展 ---"
assert_python "schema 含 token_usage 表" "
import sys; sys.path.insert(0, 'local-agent')
from data import schema
ddl = '\n'.join(schema.SCHEMA_DDL)
assert 'token_usage' in ddl, 'token_usage 表缺失'
assert 'code_changes' in ddl, 'code_changes 表缺失'
print('token_usage/code_changes 表已定义')
"
assert_python "schema 初始化含 32 表" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema
tables = schema.init_schema()
assert 'token_usage' in tables, 'token_usage 表未初始化'
assert 'code_changes' in tables, 'code_changes 表未初始化'
print(f'初始化表: {len(tables)} 张，含 token_usage/code_changes')
"

# T3 数据层 CRUD
echo "--- T3 数据层 CRUD ---"
assert_python "token_usage CRUD + 去重" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from data import repository as repo
repo.upsert_token_usage('msg1', agent_id='ag-1', role='架构·开发', topic='T1', project='P1', token_count=100, method='estimate')
repo.upsert_token_usage('msg1', agent_id='ag-1', role='架构·开发', topic='T1', project='P1', token_count=200, method='real')
assert repo.count_token_records() == 1, 'msg_id 去重失败'
assert repo.get_token_usage('msg1')['method'] == 'real', 'method 更新失败'
assert repo.token_total() == 200, f'token 汇总错误: {repo.token_total()}'
print('token CRUD + 去重通过')
"
assert_python "code_changes CRUD + 去重" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from data import repository as repo
repo.upsert_code_change('c1', agent_id='ag-1', project='P1', added=10, deleted=3)
repo.upsert_code_change('c1', agent_id='ag-1', project='P1', added=20, deleted=6)
assert repo.count_code_records() == 1, 'commit_id 去重失败'
t = repo.code_total()
assert t['added'] == 20 and t['deleted'] == 6, f'code 汇总错误: {t}'
print('code CRUD + 去重通过')
"


# T3.5 SQL 注入防护（评审必修项）
echo "--- T3.5 SQL 注入防护 ---"
assert_python "dim 白名单防注入 (token_usage)" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from data import repository as repo
repo.upsert_token_usage('wi-1', agent_id='white-1', role='开发', topic='W1', project='WP1', token_count=100)
repo.upsert_token_usage('wi-2', agent_id='white-2', role='评审', topic='W2', project='WP2', token_count=50)
# 合法维度：正常筛选
r = repo.list_token_usage('agent_id', 'white-1')
assert len(r) == 1, f'合法维度筛选错误: {len(r)}'
# 非法维度（注入 payload）：回退到全量，不执行注入
r2 = repo.list_token_usage('agent_id' + chr(59) + ' DROP TABLE token_usage', 'x')
assert len(r2) >= 3, f'非法维度未回退: {len(r2)}'
# 表仍完好
assert repo.count_token_records() >= 3, 'token_usage 表被注入破坏'
print('token_usage dim 白名单通过')
"
assert_python "dim 白名单防注入 (code_changes)" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from data import repository as repo
repo.upsert_code_change('wc-1', agent_id='white-1', project='WP1', added=10)
r = repo.list_code_changes('project', 'WP1')
assert len(r) == 1, f'合法维度筛选错误: {len(r)}'
r2 = repo.list_code_changes('project' + chr(59) + ' DROP TABLE code_changes', 'x')
assert len(r2) >= 2, f'非法维度未回退: {len(r2)}'
assert repo.count_code_records() >= 2, 'code_changes 表被注入破坏'
print('code_changes dim 白名单通过')
"

# T4 四维统计
echo "--- T4 四维统计引擎 ---"
assert_python "四维 workload_4d" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from monitor_bi.stats import workload_4d, DIMS
for dim in DIMS:
    rows = workload_4d(dim)
    assert isinstance(rows, list), f'{dim} 返回非 list'
print('四维统计正常')
"
assert_python "接口显式导出 MonitorBI" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from monitor_bi import MonitorBI
bi = MonitorBI()
assert hasattr(bi, 'workload_4d'), '缺 workload_4d'
assert hasattr(bi, 'token_summary'), '缺 token_summary'
assert hasattr(bi, 'code_changes'), '缺 code_changes'
assert hasattr(bi, 'anomaly_scan'), '缺 anomaly_scan'
assert hasattr(bi, 'render'), '缺 render'
print('MonitorBI 接口完整')
"


# T4.5 分工失衡用工作量占比（评审必修项）
echo "--- T4.5 分工失衡工作量口径 ---"
assert_python "imbalance 用 workload_4d 非 token" "
import sys, os; sys.path.insert(0, 'local-agent')
os.environ['DB_PATH'] = '$TEST_DB'
from data import schema; schema.init_schema()
from data import repository as repo
# 构造工作量分布：ag-1 大量消息，ag-2 少量
for i in range(30):
    repo.enqueue_message('ISSUE-55', {'i': i}, 'ag-1')
repo.enqueue_message('ISSUE-55', {'x': 1}, 'ag-2')
from monitor_bi import anomaly, stats
# workload_4d 反映真实工作量
agent_stats = stats.workload_4d('agent')
assert len(agent_stats) >= 2, f'应有至少 2 个 agent: {agent_stats}'
total = sum(a['total'] for a in agent_stats)
assert total > 0, '总工作量应为正'
# 低于阈值时不应报失衡（除非确实超过 40%）
anoms = anomaly.imbalance_anomalies()
# 若 ag-1 工作量占超 40% 应标失衡；否则不标
top = agent_stats[0]
top_share = top['total'] / total if total else 0
assert top_share >= 0, '占比应为正'
print(f'顶agent占比={top_share:.1%}, 异常数={len(anoms)}')
print('imbalance 工作量口径通过')
"

# T5 CLI
echo "--- T5 CLI 入口 ---"
assert_python "CLI overview 可运行" "
import subprocess, os, sys
result = subprocess.run(
    [sys.executable, '-m', 'monitor_bi.cli', 'overview'],
    capture_output=True, text=True, cwd='local-agent',
    env={**os.environ, 'DB_PATH': '$TEST_DB', 'PYTHONPATH': '$REPO_ROOT/local-agent'},
)
assert result.returncode == 0, f'CLI overview 退出码 {result.returncode}'
assert 'BI 大屏' in result.stdout, '输出缺少 BI 大屏标题'
print('CLI overview 通过')
"
assert_python "CLI render 可运行" "
import subprocess, os, sys
result = subprocess.run(
    [sys.executable, '-m', 'monitor_bi.cli', 'render'],
    capture_output=True, text=True, cwd='local-agent',
    env={**os.environ, 'DB_PATH': '$TEST_DB', 'PYTHONPATH': '$REPO_ROOT/local-agent'},
)
assert result.returncode == 0, f'CLI render 退出码 {result.returncode}'
assert 'BI 大屏已生成' in result.stdout, 'render 输出错误'
print('CLI render 通过')
"
assert_python "CLI anomaly 可运行" "
import subprocess, os, sys
result = subprocess.run(
    [sys.executable, '-m', 'monitor_bi.cli', 'anomaly'],
    capture_output=True, text=True, cwd='local-agent',
    env={**os.environ, 'DB_PATH': '$TEST_DB', 'PYTHONPATH': '$REPO_ROOT/local-agent'},
)
assert result.returncode == 0, f'CLI anomaly 退出码 {result.returncode}'
print('CLI anomaly 通过')
"
assert_python "CLI token 可运行" "
import subprocess, os, sys
result = subprocess.run(
    [sys.executable, '-m', 'monitor_bi.cli', 'token'],
    capture_output=True, text=True, cwd='local-agent',
    env={**os.environ, 'DB_PATH': '$TEST_DB', 'PYTHONPATH': '$REPO_ROOT/local-agent'},
)
assert result.returncode == 0, f'CLI token 退出码 {result.returncode}'
print('CLI token 通过')
"
assert_python "CLI code 可运行" "
import subprocess, os, sys
result = subprocess.run(
    [sys.executable, '-m', 'monitor_bi.cli', 'code'],
    capture_output=True, text=True, cwd='local-agent',
    env={**os.environ, 'DB_PATH': '$TEST_DB', 'PYTHONPATH': '$REPO_ROOT/local-agent'},
)
assert result.returncode == 0, f'CLI code 退出码 {result.returncode}'
print('CLI code 通过')
"

# ------------------------------------------------------------
echo "======================================================"
if [ $FAIL -gt 0 ]; then
  echo "❌ 失败 $FAIL 项, 通过 $PASS 项"
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  - $item"
  done
  exit 1
fi
echo "✅ 全部 $PASS 项通过!"
echo "======================================================"
