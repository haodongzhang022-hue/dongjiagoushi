# 经验记忆库 + 语义向量触发（memory 模块）

> 本文件是「架构师 Agent」经验记忆库与语义向量触发模块的说明与维护入口。
> 它把「语义向量触发」从 **prompt/关键词层面** 升级为 **专业可靠的真实向量检索 + 持久化记忆库**。

---

## 一、解决的问题

协作触发三层机制中的「② 语义向量触发」此前停留在 **人设/文档语义映射表（prompt 层面）**，
尚未接真实 embedding 分类器。而用户（张浩东）明确指出：

> 存储记忆本身也得 RAG；我们要做的不是轻量级，而是**专业可靠**；
> 需要有**数据库**，甚至**持续积累经验**是必要的能力；
> 需要做 **LanceDB 和云端的你自带的数据库的双兼容**，给他们用**相同格式**。

本模块据此落地为一个**专业可靠的记忆库 + 语义触发引擎**。

## 二、架构与能力

```
                          ┌───────────────────────────────┐
                          │         MemoryStore          │
                          │   （统一接口，按 backend 路由）  │
                          └───────┬──────────┬───────────┘
                          backend │          │ backend
                    ┌─────────────▼──┐  ┌────▼────────────┐
                    │   LanceDB 本地  │  │  云端 CNB 知识库  │
                    │  （持久化向量库） │  │ （RAG，同格式适配） │
                    └───────┬────────┘  └────┬────────────┘
                            │   相同格式     │
                            │  MemoryRecord  │
                            └── UnifiedSchema┘
```

| 能力 | 说明 |
|------|------|
| **统一向量格式** | `MemoryRecord / UnifiedSchema`（id/role/category/text/vector/meta/created_at），本地与云端共用同一契约（"相同格式"） |
| **本地 LanceDB 后端** | 持久化向量库，可离线、增删改查、向量余弦检索、持续积累经验 |
| **云端 CNB 知识库后端** | 将记录序列化为**同格式** Markdown/JSONL 块，交由 CNB `knowledge:update`（RAG，hunyuan embedding）入库 |
| **双写兼容（dual）** | 本地 + 云端同格式同时写入，满足"双兼容" |
| **语义向量触发引擎** | 输入 → 向量化 → 与角色语义原型做余弦相似度 → 命中最高者触发角色（真实向量检索，非关键词） |
| **持续积累经验** | 每次协作交互（接力/回转/触发）写入记忆库，语义触发随积累增强，可检索回溯 |
| **可插拔 embedding** | 默认离线哈希向量（零依赖、CI 可复现）；**已接入真实语义模型**（sentence-transformers，`get_embedder("sentence")`），输出维度与哈希一致、可无缝替换，未安装时自动回退哈希兜底 |

## 三、目录结构

```
src/memory/
├── __init__.py                # 模块导出
├── schema.py                  # ⭐ 统一向量格式（MemoryRecord/UnifiedSchema/角色语义原型/哈希向量/余弦）
├── store.py                   # MemoryStore 门面（lancedb/cloud/dual 后端路由）
├── triggers.py                # SemanticTriggerEngine（显式[触发]+语义向量触发+结合记忆库二次确认）
├── cli.py                     # 命令行入口
├── requirements.txt           # 依赖（lancedb/numpy）
├── backends/
    ├── __init__.py
    ├── embedding.py           # EmbeddingProvider 接口 + get_embedder 工厂（hash/sentence）
    ├── sentence_embedding.py  # ⭐ 真实语义 embedding（sentence-transformers，随机投影对齐维度 + 哈希回退）
    ├── lancedb_backend.py     # LanceDBBackend（本地持久化向量库）
    └── cloud_backend.py       # CloudBackend（云端 CNB 知识库同格式适配）
```

## 四、统一向量格式（MemoryRecord，本地/云端共用）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 记录主键（`role:{role}:{seq}`） |
| `role` | str | 归属/触发角色（架构·产品/开发/评审/测试/总师） |
| `category` | str | 内容类型（semantic_trigger / experience / context） |
| `text` | str | 原始文本（输入/记忆/交互记录） |
| `vector` | list | 向量（默认维度 256；可替换真实模型） |
| `meta` | dict | 结构化元信息（来源/时间/状态） |
| `created_at` | str | 记录时间（ISO8601） |

**角色语义原型**（触发基准，定义于 `schema.ROLE_PROTOTYPES`）：每个角色一段职责语义文本 → 生成该角色语义中心向量，触发时输入向量与之比对。

## 五、如何使用

```bash
# 安装依赖
pip install -r src/memory/requirements.txt

# 命令行：写入一条经验到 LanceDB 本地库
python3 -m memory.cli add --role 架构·开发 --text "实现 auth 登录接口" --backend lancedb

# 命令行：语义向量触发（看应触发哪个角色）
python3 -m memory.cli trigger --text "帮我评审这段代码有没有bug"

# 命令行：双写（本地 LanceDB + 云端同格式）
python3 -m memory.cli add --role 架构·测试 --text "测试矩阵全绿" --backend dual
```

```python
import sys; sys.path.insert(0, "src")
from memory import MemoryStore, SemanticTriggerEngine, MemoryRecord
from memory.schema import hash_embedding, now_iso

# 1. 语义向量触发（真实向量检索）
eng = SemanticTriggerEngine()
print(eng.trigger("写一个登录接口"))      # → 架构·开发
print(eng.trigger("[触发:架构·评审] 看看"))  # → 显式优先，架构·评审

# 2. 本地 LanceDB 记忆库 + 持续积累
store = MemoryStore(backend="lancedb", path="./.memory")
store.add([MemoryRecord(id="r1", role="架构·开发", category="experience",
                        text="实现 auth 登录接口", vector=hash_embedding("实现 auth 登录接口"),
                        meta={}, created_at=now_iso())])
# 3. 结合记忆库二次确认
print(eng.trigger_with_memory("实现登录接口", store))
store.close()
```

## 六、测试与验收（T9）

`tests/test_memory_store.sh`（T9）端到端可复现，已纳入 `.cnb.yml` 的 test 阶段信号灯：

| 场景 | 断言 |
|------|------|
| A 语义向量触发 | 无显式 `[触发]` 也能按职责语义命中正确角色（开发/评审/产品/测试） |
| B 显式触发 | `[触发:角色]` 优先级最高 |
| C 本地 LanceDB | 写入/检索/计数/持久化（重开连接仍可读） |
| D 云端后端 | 同格式写入/检索 + Markdown 往返解析 + 导出 md/jsonl |
| E 双兼容 | LanceDB + 云端同格式双写 |
| F 持续积累经验 | 多次写入 → 语义触发结合记忆库二次确认 |

本地运行：

```bash
bash tests/test_memory_store.sh
```

## 七、与知识库（RAG）的关系

- **本地 LanceDB**：开发/实验期本地记忆，可离线、可持久化、可积累。
- **云端 CNB 知识库**：`knowledge:update`（hunyuan embedding，RAG），架构师对话直接检索。
- **同一套 MemoryRecord 格式**：两端存储的是同一种记录，只是引擎不同；`dual` 后端可双写对齐。

> 说明：默认向量为离线哈希向量（零依赖、CI 可复现、语义弱区分度），适合触发原型与双后端对齐验证；
> **生产环境请挂接真实 embedding 模型**——已内置 `get_embedder("sentence")`（sentence-transformers），
> 安装 `pip install -r src/memory/requirements.txt` 后即可启用，输出维度与哈希一致、无缝替换；
> 未安装时自动回退哈希，CI / 离线不崩。
