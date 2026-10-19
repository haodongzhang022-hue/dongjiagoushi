# -*- coding: utf-8 -*-
"""
数据管理层 · 数据库连接层（db）
================================
本模块是本仓库 **数据架构升级** 的核心底座，把原来「单文件接力卡 / 分片 JSON /
进程内 dict」的简单状态存储，升级为**真正的关系型数据库承载**，以支撑
最大 **2500 个并发 agent** 之间的信息互通与持久化：

  - 内容存档（agents 档案 / 协作产出归档）
  - 进度统计（progress 进度 / stats 指标聚合）
  - 消息管线（messages 消息队列，可追踪、可回放）
  - 任务存储（tasks 任务分解与状态流转）

后端抽象（多级可伸缩）：
  - sqlite（默认，Python 标准库零依赖）：单机开发/中小规模，表结构完备，天然支持
    事务、索引、并发读；写并发用「短事务 + WAL」缓解，满足单机数百级协作。
  - postgresql（可选，需 psycopg2）：分布式/生产，支撑 2500 级强一致协作，
    **仓储接口与表结构已抽象为同一套**（`DB_BACKEND=postgresql://...`）；
    但 **PG 写路径端到端尚未闭环**（方言 DDL/`SERIAL`、`?` 参数风格、事务内
    `db.execute` 连接复用均未打通，见 ADR-0013「跟踪项」）——**默认后端为 sqlite，
    CI 全走 sqlite**，切 PG 前请先确认该跟踪项已收口，勿按「无缝」预期直接上生产。
  - redis（可选，消息队列高速缓存）：用于大规模下消息管线的吞吐增强，
    `BROKER_BACKEND=redis` 时消息落 Redis 队列，进度/任务/存档仍落关系库。

设计原则：
  1. **零依赖可用**：默认 sqlite 用标准库 sqlite3，CI / 离线开箱即用；
     依赖后端缺失时优雅降级到 sqlite，绝不因缺依赖崩掉。
  2. **同一套 schema / repository（接口层）**：SQLite 与 PostgreSQL 共用表结构与仓储
     接口，通过 `DB_URL` 切换；**但 PG 写路径闭环仍为跟踪项**（方言 DDL/参数风格/
     事务内 `db.execute` 连接复用未打通），非「零成本无缝」——见 ADR-0013。
  3. **数据管理员 agent 负责**：本层数据的写入/校验/统计/归档由
     「架构·数据管理员」角色（见 roles.d/data_admin.py 与 docs/DATA_ARCHITECTURE.md）
     统一负责，人类/总师只俯瞰二级信息。

通过环境变量切换后端：
  - DB_BACKEND   sqlite | postgresql | mysql（mysql 预留）
  - DB_PATH       sqlite 库文件路径（默认 local-agent/data/runtime.db，可被 .gitignore 忽略）
  - DB_URL        兼容 sqlalchemy 的数据库连接串（postgresql://user:pass@host:5432/db）
"""
import os
import sqlite3
import threading
import weakref
from datetime import datetime

# ---- 后端选择 ----
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_DATA_DIR, "runtime.db"))
DB_URL = os.environ.get("DB_URL", "")

# sqlite 连接：按线程隔离（每个线程独立连接，避免跨线程共用）
_thread_local = threading.local()


def _iso_now():
    return datetime.utcnow().isoformat()


def _connect_sqlite():
    """建立/复用当前线程的 sqlite 连接（WAL 模式，支持并发读写）。"""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.isolation_level = None  # 显式事务控制（BEGIN IMMEDIATE / COMMIT）
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")     # 写并发友好
        conn.execute("PRAGMA synchronous=NORMAL")   # 平衡持久性与性能
        conn.execute("PRAGMA busy_timeout=5000")    # 写锁等待
        _thread_local.conn = conn
    return conn


def _connect_sqlalchemy():
    """通过 sqlalchemy 连接非 sqlite 后端（postgresql / mysql）。"""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "启用非 sqlite 后端需安装 sqlalchemy + 对应驱动。"
            "SQLite 为默认零依赖后端，可直接使用。"
        ) from e
    url = DB_URL or DB_BACKEND
    engine = getattr(_thread_local, "engine", None)
    if engine is None or str(engine.url) != url:
        engine = create_engine(url, pool_pre_ping=True)
        _thread_local.engine = engine
    return engine


def connect():
    """返回当前线程的连接对象（sqlite conn 或 sqlalchemy engine）。"""
    if DB_BACKEND in ("postgresql", "mysql"):
        return _connect_sqlalchemy()
    return _connect_sqlite()


def backend():
    """当前生效的后端名。"""
    return DB_BACKEND


def is_remote():
    """是否远程/分布式后端。"""
    return DB_BACKEND in ("postgresql", "mysql")


def _depth():
    """当前线程的事务嵌套深度（0 = 不在事务中）。"""
    return getattr(_thread_local, "tx_depth", 0)


def is_in_tx():
    """只读探针：当前线程事务计数是否 > 0（**不**用 conn.in_transaction 判据）。

    CPython sqlite3 在 `isolation_level=''` 下自己开隐式事务，`in_transaction`
    常态为 True，拿它判「是否在事务中」会把正常状态误判成遗弃。本函数只读计数。

    生产用途：`data-cli status` 用它输出当前线程事务态（诊断「写没进事务 /
    depth 是否泄漏」），而非只看 `in_transaction` 被常态 True 误导。
    """
    return _depth() > 0


def tx_depth():
    """公开探针：当前线程事务嵌套深度（0 = 不在事务中）。

    `is_in_tx()` 只回答"有没有"，回答不了"漏了几层"；诊断 tx_depth 泄漏要的是后者。
    对外公开它，测试与 `data-cli status` 就不必去抠私有符号（重构私有名时不至于碎）。
    """
    return _depth()


def alive_tx_frames():
    """公开探针：当前线程**存活**事务对象数（遗弃判据的另一半）。

    `tx_depth > alive_tx_frames()` 就是「有层被遗弃」的完整口径——诊断/测试据此判断
    兜底是否成立，不必去读私有帧栈。
    """
    return len(_alive_frames())


def reclaim_abandoned_tx(force=False):
    """公开入口：回收遗弃事务残留（语义见 `_reclaim_abandoned_tx`）。

    生产路径已自动调用（开新事务前 / 最外层收尾时），本函数给诊断与测试一个**公开**
    抓手，避免外部为了验证兜底去 import 私有符号。返回 True = 本次真动了计数/清帧。
    """
    return _reclaim_abandoned_tx(force=force)


def execute(sql, params=()):
    """执行一条写语句（insert/update/delete），返回受影响行数。

    **远程后端（PG/MySQL）在事务内调用本函数会 fail-loud 抛错**：本函数每次都在
    新连接上另开事务（`eng.begin()`），无法复用当前 `db.transaction()` 的连接——
    若放任其「成功」，调用方会以为写进了当前事务、实则独立提交，事务静默失去
    原子性（实测：`with db.transaction(): db.execute(INSERT); raise` 残留 1 行）。
    事务内请改用 `tx.execute()`（真复用事务连接）。见 ADR-0013 跟踪项。
    """
    if DB_BACKEND in ("postgresql", "mysql"):
        if _depth() > 0:
            raise RuntimeError(
                "远程后端的事务内不支持 db.execute()：它会在独立连接上另开事务，"
                "静默失去原子性（PG 写路径闭环为 ADR-0013 跟踪项，未实现连接复用）。"
                "请在事务内改用 tx.execute(...)，或使用默认 sqlite 后端。")
        from sqlalchemy import text

        eng = connect()
        with eng.begin() as conn:
            res = conn.execute(text(sql), params)
            return res.rowcount if res.rowcount is not None else 0
    conn = connect()
    cur = conn.execute(sql, params)
    if _depth() <= 0:
        conn.commit()
    return cur.rowcount


def query(sql, params=()):
    """执行一条查询，返回 list[dict]。"""
    if DB_BACKEND in ("postgresql", "mysql"):
        from sqlalchemy import text

        eng = connect()
        with eng.connect() as conn:
            rows = conn.execute(text(sql), params)
            return [dict(r._mapping) for r in rows]
    conn = connect()
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def query_one(sql, params=()):
    """执行一条查询，返回单条 dict 或 None。"""
    rows = query(sql, params)
    return rows[0] if rows else None


def transaction():
    """返回一个上下文管理器，包裹一批写操作（原子提交/回滚）。"""
    if DB_BACKEND in ("postgresql", "mysql"):
        if _depth() > 0:
            raise RuntimeError(
                "远程后端不支持嵌套 db.transaction()：每次都会从连接池取新连接、"
                "另开事务，无法与外层同事务（ADR-0013 跟踪项）。请只保留最外层事务。")
        eng = connect()
        depth = _depth() + 1
        # 先构造（含 ctx.__enter__()，可能抛错）再落 depth：构造失败不留残计数
        tx = _SQLA_Tx(eng.begin(), depth)
        _thread_local.tx_depth = depth
        return tx
    # 新事务即将开启：先回收**遗弃**残留（非 with + 中途异常丢对象会留下脏计数）。
    # force 不可无条件：那会把活着的嵌套事务误判成遗弃，内层随之退化成 L1、
    # 显式收尾也不再抛错（「以为回滚了、其实落库了」的陷阱会复活）。
    # 判据：**开新事务的时刻不该有活事务**；若帧全空而计数 > 0 → 必是遗弃。
    _reclaim_abandoned_tx(force=True)
    conn = connect()
    depth = _depth()
    if depth == 0:
        conn.execute("BEGIN IMMEDIATE")  # 立即取写锁，读-改-写期间不被他人插入
    tx = _SQLite_Tx(conn, depth + 1)
    _thread_local.tx_depth = depth + 1
    return tx


def _tx_stack():
    """当前线程**存活**事务对象的弱引用列表。

    计数 `tx_depth` 只管「嵌套层数」，分不清「还在用的内层」与「已被丢弃的残骸」。
    存活帧补上这一维。**必须用 weakref**：强引用会让「被调用方丢弃的事务对象」
    看起来仍然存活，遗弃与正常嵌套就分不开了（实测：强引用列表下 `del tx` 计数
    与帧都不变，兜底永远不触发）。走弱引用后「对象被丢弃 → 引用自动失效」，
    `计数 > 存活引用数` 才是**真有层被遗弃**。
    """
    stack = getattr(_thread_local, "tx_stack", None)
    if stack is None:
        stack = []
        _thread_local.tx_stack = stack
    return stack


def _alive_frames():
    """存活事务对象（清掉已失效的弱引用）。"""
    stack = _tx_stack()
    stack[:] = [r for r in stack if r() is not None]
    return [r() for r in stack]


def _drop_frame(tx):
    """摘下 tx 的存活帧（按身份比对，防 `id()` 复用误摘）。"""
    stack = _tx_stack()
    stack[:] = [r for r in stack if r() is not None and r() is not tx]


def _reclaim_abandoned_tx(force=False):
    """回收**遗弃事务**残留的事务计数（best-effort）。

    返回值语义**单一**：True = 本次真的动了计数/清了残帧，False = 什么都没改。
    不再有"清理成功却返回 False"的分支（曾让调用方无法凭返回值判断有没有回收）。

    `_thread_local.tx_depth` 靠 tx 对象收尾递减，非 `with` 用法下若中途异常、
    对象被丢弃而未收尾，计数就永久残留：之后 `db.execute` 不再自动提交、
    `BEGIN IMMEDIATE` 不再取写锁 —— 事务**静默失去原子性**（正是 M1 要消灭的
    「假原子性」），且下一次 `with` 正常退出也可能**不落库**。

    **判据用「存活帧数」，不用 `conn.in_transaction`**：CPython sqlite3 在
    `isolation_level=''` 下会自己开隐式事务，`in_transaction` 常态为 True ——
    拿它当判据会把正常状态误判成遗弃，反而丢掉最外层 commit。也不单看计数：
    `计数 == 存活帧数` 才是正常嵌套，只有「计数 > 存活帧数」才真有层被遗弃。

    `force=True` 只允许在**不该有任何活事务**的时刻调用（开新事务前）：此时
    `计数 > 0 且 存活帧 == 0` 即遗弃；计数归零而帧没摘则是残留帧，一并清理。
    """
    depth = getattr(_thread_local, "tx_depth", 0)
    stack = _alive_frames()
    if force:
        if depth <= 0:
            if not stack:
                return False          # 无计数、无残帧 → 干净，没动手
            del _tx_stack()[:]        # 计数已归零、帧没摘 → 残留帧，清掉
            return True               # 动了手就要如实说（返回值语义统一）
        if not stack:
            # 帧全空而计数 > 0：唯一的解释是遗弃（活事务必有帧）
            try:
                connect().rollback()
            except Exception:
                pass
            _thread_local.tx_depth = 0
            return True
        return False                  # 有活帧 → 正常嵌套/可信残留，交回正常路径
    if depth <= 0 or depth <= len(stack):
        return False                  # 无残留 / 计数与存活帧自洽（正常嵌套）→ 不动

    # 遗弃层无人能收尾 → 统一回滚（若有未提交写，宁可丢弃也不静默半提交）
    try:
        connect().rollback()
    except Exception:
        pass
    _thread_local.tx_depth = len(stack)
    return True


class _SQLite_Tx:
    """sqlite 事务上下文（延迟提交/回滚）。

    `tx_depth` 是事务嵌套计数：只有最外层（depth 归零）才真正 commit/rollback。
    **commit()/rollback() 与 __exit__ 共用同一条收尾路径**——否则非 `with`
    用法（`tx = db.transaction(); tx.commit()`）会把 depth 永久留在 1，
    之后 `db.execute` 不再自动提交、`BEGIN IMMEDIATE` 不再取写锁，
    事务静默失去原子性（正是 M1 要消灭的「假原子性」）。

    **嵌套语义**：sqlite 无真正嵌套事务，内层 `with` 退出只是不提交（交给最外层），
    异常会冒泡到最外层统一回滚。内层**显式** `commit()/rollback()` 无法作用于
    已提交的外层，故直接抛错——不静默吞掉「以为回滚了、其实落库了」的陷阱。
    """

    def __init__(self, conn, depth=1):
        self._conn = conn
        self._depth = depth          # 本层事务的嵌套深度（1 = 最外层）
        self._closed = False
        _tx_stack().append(weakref.ref(self))   # 弱引用登记存活帧（与 tx_depth 对应）

    def commit(self):
        self._finish("commit", explicit=True)

    def rollback(self):
        self._finish("rollback", explicit=True)

    def _finish(self, action, explicit=False):
        """收尾：depth 递减；最外层才落 commit/rollback。幂等，重复调用无副作用。"""
        if self._closed:
            # 重复收尾：本层已归零，但若是**中途异常导致对象被遗弃**后又被显式收尾，
            # 计数可能仍残留 → 先回收遗弃层，再视为无操作（不重放 commit/rollback）。
            _reclaim_abandoned_tx()
            return
        # **判据必须在回收之前**：本层自己是内层（depth>1）就要抛错，与计数是否
        # 被他人污染无关——先回收会把计数清零，令 `depth>1` 判据失效（曾经的回归）。
        if explicit and self._depth > 1:
            raise RuntimeError(
                "嵌套事务不支持显式 %s()：只有最外层事务能提交/回滚。"
                "内层请直接退出 with（异常会冒泡到最外层回滚）。" % action)
        # 本层是最外层且要收尾 → 顺手把**遗弃层**残留回收（它们无人能收尾，
        # 残留下去会让后续事务跳过 BEGIN IMMEDIATE、静默失去原子性）。
        _reclaim_abandoned_tx()
        self._closed = True
        _drop_frame(self)
        # 按本层深度收敛（不用「当前深度-1」：内层显式调用抛错时不会走 __exit__，
        # 用「当前深度-1」会让计数永久留 1，之后事务静默失去原子性）。
        depth = self._depth - 1
        _thread_local.tx_depth = depth
        if depth == 0:
            getattr(self._conn, action)()

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._closed:
            return False
        _drop_frame(self)
        depth = self._depth - 1
        _thread_local.tx_depth = depth
        self._closed = True
        if depth > 0:
            return False  # 内层不提交，交给最外层
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


class _SQLA_Tx:
    """sqlalchemy 事务适配。

    `Engine.begin()` 返回的是 `_GeneratorContextManager`，**自身没有 commit/rollback**
    （提交/回滚落在 `__enter__` 返回的 `Connection` 上）。因此这里保存
    `__enter__` 拿到的连接，显式 commit/rollback 走连接——否则调用
    `tx.commit()` 直接 `AttributeError`（pg 写路径实测挂在这）。

    **事务内必须用 `tx.execute()`**：`db.execute()` 会在独立连接上另开事务，
    无法复用本事务连接（故对远程后端在事务内调用直接 fail-loud 抛错，见 `execute()`）。
    `tx_depth` 与 sqlite 分支同口径，退出时归零。
    """

    def __init__(self, ctx, depth=1):
        self._ctx = ctx
        self._conn = ctx.__enter__()
        self._depth = depth          # 远程不支持嵌套，恒为 1
        self._closed = False

    def _finish(self, exc_type=None, exc=None, tb=None):
        """收尾：depth 归零 + 交回 `_GeneratorContextManager` 收尾；幂等。

        **显式 commit/rollback 与 `with` 退出共用这一条路径**——都走
        `self._ctx.__exit__`，由上下文管理器负责真正的 commit/rollback **以及
        连接的归还**（直接调 `conn.commit()` 而不退 ctx，会让生成器持有的连接
        迟迟不还池）。这样 `tx = db.transaction(); tx.commit()` 的非 with 用法
        与 `with db.transaction():` 行为一致，也不会漏计数。
        """
        if self._closed:
            return False
        self._closed = True
        _thread_local.tx_depth = max(0, self._depth - 1)
        return self._ctx.__exit__(exc_type, exc, tb)

    def commit(self):
        self._finish(None, None, None)

    def rollback(self):
        # 用异常退出让 ctx 走回滚分支（正常退出会 commit）
        self._finish(RuntimeError, RuntimeError("explicit rollback"), None)

    def execute(self, sql, params=()):
        from sqlalchemy import text

        return self._conn.execute(text(sql), params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._finish(exc_type, exc, tb)


def now_iso():
    return _iso_now()
