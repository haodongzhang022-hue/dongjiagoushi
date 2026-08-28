
## IncrementalSelector（T2）

基于 git diff 的变更感知增量选择器。

### 核心接口

```python
from hybrid.selector import IncrementalSelector
s = IncrementalSelector(root_dir=".")

# git diff 获取变更文件
files = s.changed_files("HEAD~1", "HEAD")

# 变更文件 → 受影响测试（含依赖传播）
selected = s.select(["collab/engine.py"])
# -> ['local-agent/tests/test_collab.sh',
#     'local-agent/tests/test_peer_collab.sh',
#     'local-agent/tests/test_peer_closure.sh']

# 一键增量选择
selected = s.incremental()  # 默认比较 HEAD~1..HEAD

# 工作区未提交变更
selected = s.incremental_workdir()

# 全量兜底
suite = s.full_suite()
```

### 依赖传播防漏测

```
test_collab  covers collab/engine.py
test_peer_collab depends_on test_collab
test_peer_closure depends_on test_peer_collab

变更 collab/engine.py → 运行 [test_collab, test_peer_collab, test_peer_closure]
```
