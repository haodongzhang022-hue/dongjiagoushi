# -*- coding: utf-8 -*-
"""
memory.schema —— 统一向量格式（本地 LanceDB 与云端知识库共用同一契约）

设计要点（"相同格式"）：
  本地 LanceDB 与云端 CNB 知识库存储的是同一类记录，字段命名与含义一致，
  仅底层存储引擎不同。本文件定义这套统一 schema，让两套后端可互相迁移/对齐。

字段说明（UnifiedSchema / MemoryRecord）：
  id           记录主键（由模块内生成，如 role:{role}:{seq}）
  role         触发/归属的协作角色（架构·产品 / 架构·开发 / 架构·评审 / 架构·测试 / 架构·总师）
  category     内容类型（semantic_trigger 语义触发原型 / experience 经验 / context 上下文）
  text         原始文本（输入 / 记忆 / 交互记录）
  vector       向量（统一维度，见 EMBEDDING_DIM；默认离线哈希向量，可替换为真实模型）
  meta         结构化元信息（JSON，记录来源/时间/状态等，云端 RAG 可检索）
  created_at   记录时间（ISO8601）

与云端对齐的说明：
  - 云端 CNB 知识库（knowledge:update）以"文档切片 + hunyuan embedding"入库，
    检索靠 RAG。本地库对齐为"同一条 text → 同一种语义向量"。
  - 因此本模块的"云端后端"将 MemoryRecord 序列化为 Markdown/JSON 文档块，
    交给 CNB knowledge 入库（同格式，不同引擎）。详见 backends/cloud.py。
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict

# 统一向量维度：离线哈希向量的维度；接入真实 embedding 模型时可保持同一维度契约
EMBEDDING_DIM = 256

# 记忆库集合名（LanceDB 表名 / 云端知识库集合名），两端保持一致
COLLECTION_NAME = "arch_memory"

# 协作角色（与 .cnb/settings.yml 命名严格一致）
ROLES = ["架构·总师", "架构·产品", "架构·开发", "架构·评审", "架构·测试"]


@dataclass
class UnifiedSchema:
    """统一向量格式的字段契约（作为 schema 声明 / 文档契约）。"""

    id: str = ""
    role: str = ""
    category: str = "context"
    text: str = ""
    vector: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    created_at: str = ""

    def to_record(self) -> "MemoryRecord":
        return MemoryRecord(**asdict(self))

    @staticmethod
    def example() -> "MemoryRecord":
        """给出一份示例记录，用作 schema 对齐/测试基准。"""
        return MemoryRecord(
            id="role:架构·开发:000001",
            role="架构·开发",
            category="semantic_trigger",
            text="用户要求实现 auth 模块登录接口，边界仅后端，验收=单测通过。",
            vector=hash_embedding("用户要求实现 auth 模块登录接口"),
            meta={"source": "test", "status": "done"},
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


@dataclass
class MemoryRecord:
    """一条记忆记录（本地 LanceDB 行 / 云端知识块 的统一表示）。"""

    id: str = ""
    role: str = ""
    category: str = "context"
    text: str = ""
    vector: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        """序列化为 Markdown 文档块，供云端 CNB 知识库入库（同格式不同引擎）。"""
        return (
            f"### memory:{self.id}\n"
            f"- role: {self.role}\n"
            f"- category: {self.category}\n"
            f"- created_at: {self.created_at}\n"
            f"- meta: {json.dumps(self.meta, ensure_ascii=False)}\n\n"
            f"{self.text}\n"
        )

    @staticmethod
    def from_markdown(block: str) -> "MemoryRecord":
        """从 Markdown 文档块解析回 MemoryRecord（云端→本地对齐）。"""
        rec = MemoryRecord()
        for line in block.splitlines():
            if line.startswith("### memory:"):
                rec.id = line[len("### memory:"):].strip()
            elif line.startswith("- role: "):
                rec.role = line[len("- role: "):].strip()
            elif line.startswith("- category: "):
                rec.category = line[len("- category: "):].strip()
            elif line.startswith("- created_at: "):
                rec.created_at = line[len("- created_at: "):].strip()
            elif line.startswith("- meta: "):
                try:
                    rec.meta = json.loads(line[len("- meta: "):].strip())
                except Exception:
                    rec.meta = {}
        # 正文为第一行非元信息行
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(("#", "-"))]
        if lines:
            rec.text = "\n".join(lines)
        return rec


def hash_embedding(text: str, dim: int = EMBEDDING_DIM) -> list:
    """离线确定性哈希向量（零依赖、可复现、跨环境一致）。

    说明：
      - 这是"语义向量"的离线兜底实现，保证本地测试与 CI 可复现、无模型下载成本。
      - 生产环境可替换为真实 embedding 模型（如云端 Hunyuan / 本地 sentence-transformers），
        只需实现 EmbeddingProvider 接口并保持同维度即可（见 backends/embedding.py）。
      - 哈希向量对语义有弱区分度，但足够用于角色语义触发原型与双后端对齐验证；
        真实场景请挂接 embedding 模型以获强语义。
    """
    vec = [0.0] * dim
    tokens = _tokenize(text)
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign
    norm = (sum(v * v for v in vec) ** 0.5) or 1.0
    return [v / norm for v in vec]


def _tokenize(text: str) -> list:
    """简易中英文分词：中文按字、英文按词，去停用词。"""
    stops = {"的", "了", "是", "在", "和", "与", "及", "为", "之", "我", "你",
             "他", "她", "它", "要", "把", "被", "对", "向", "从", "到", "让",
             "the", "a", "an", "is", "are", "to", "of", "for", "and", "or", "in", "on"}
    tokens = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            tokens.append(ch)
        elif ch.isalnum():
            tokens.append(ch)
    words = []
    for tok in tokens:
        if tok not in stops:
            words.append(tok)
    return words if words else ["__blank__"]


def new_id(role: str, seq: int) -> str:
    """生成唯一记录 id。"""
    return f"role:{role}:{seq:06d}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# 角色语义原型（语义向量触发的基准）
# 每个角色一段职责语义文本 → 生成该角色的"语义中心向量"。
# 触发时，输入文本向量化后与各角色原型向量做余弦相似度，命中最高者即触发。
# ---------------------------------------------------------------------------
ROLE_PROTOTYPES = {
    "架构·产品": "需求澄清与拆分，把模糊需求转化为可验收的需求规格与用户故事",
    "架构·开发": "实现方案与编码，写代码、实现接口、提交 PR、自测并留痕，编写后端与功能代码",
    "架构·评审": "代码评审与质量把关，检查安全漏洞、Bug、代码质量，可打回转",
    "架构·测试": "测试与联调，构造测试矩阵、跑信号灯、验证功能是否达成预期",
    "架构·总师": "架构设计与编排，调研、拓扑、可行性、方案、分工、进度、索引、汇报",
}


def role_prototype_vector(role: str) -> list:
    """返回某角色的语义原型向量（离线哈希）。"""
    return hash_embedding(ROLE_PROTOTYPES.get(role, role))


def cosine(a: list, b: list) -> float:
    """余弦相似度（本地/云端共用）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a) ** 0.5) or 1.0
    nb = (sum(y * y for y in b) ** 0.5) or 1.0
    return dot / (na * nb)
