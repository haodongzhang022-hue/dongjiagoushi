# -*- coding: utf-8 -*-
"""
调度中枢 · 外部事件源安全认证（security）
========================================
多终端外部事件源（本地电脑 / 手机 / 虚拟机 / 沙盒 / 上位机）接入 Webhook 接收端时，
必须先通过安全认证。用户拍板：**秘钥 key + IP 白名单** 形式；`webhook 更合理`。

安全机制（每一条都可独立演进、可留痕）：
  - ① 秘钥认证（key）：每个外部源注册一个独立 API key，请求头带 `X-API-Key`，
    接收端用**常数时间比较**校验，防时序侧信道；
  - ② IP 白名单（whitelist）：每个外部源可绑定一个/多个来源 IP / CIDR 段，
    非白名单 IP 一律拒绝；支持 `0.0.0.0/0`（代表不限 IP，仅靠 key）；
  - ③ 源级授权（per-source）：key + IP 与**事件源名绑定**，防止「一个 key 冒充
    多个源」——多终端各自独立授权、互不越权；
  - ④ 认证审计（audit）：每次认证成功/失败都留痕到 `external_auth` 表，
    供 Web 面板俯瞰「谁在什么时候从哪个 IP 打了哪个 key」；失败即拦截并记录。

设计原则：
  - 安全是**入口闸门**：认证不通过，事件绝不进入规则引擎/派发链路；
  - 多源不共钥：手机、虚拟机、沙盒、上位机各自独立 key + 独立 IP 白名单；
  - 默认拒绝（deny-by-default）：未登记的外部源一律拒绝，不猜测放行。
"""
import hmac
import ipaddress
import os
import uuid

from data import db


def _now():
    return db.now_iso()


def _secure_compare(a, b):
    """常数时间字符串比较（防时序侧信道）。"""
    a = (a or "").encode("utf-8")
    b = (b or "").encode("utf-8")
    return hmac.compare_digest(a, b)


def _is_in_whitelist(ip, whitelist):
    """判断一个来源 IP 是否命中白名单（支持单 IP 与 CIDR 段；空/0.0.0.0/0 = 不限）。"""
    if not whitelist:
        return False
    try:
        src = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist:
        entry = (entry or "").strip()
        if not entry:
            continue
        if entry in ("0.0.0.0/0", "*"):
            return True  # 不限 IP（仅靠 key）
        try:
            if "/" in entry:
                net = ipaddress.ip_network(entry, strict=False)
                if src in net:
                    return True
            elif str(src) == entry:
                return True
        except ValueError:
            continue
    return False


def gen_key():
    """生成一个秘钥（供登记外部源时用）。返回 (key, 明文展示)。"""
    return f"sk-{uuid.uuid4().hex}"


# ---- 外部源登记（数据表 external_sources）----
def register_source(name, key=None, ip_whitelist=None, kind="webhook", meta=None):
    """登记一个外部事件源，绑定独立秘钥 + IP 白名单。

    - name：外部源名（如 local_pc / phone / vm / sandbox / host_upper）；
    - key：该源的 API key；不传则自动生成；
    - ip_whitelist：允许的来源 IP / CIDR 列表；
    - kind：外部源类型（webhook / poll / host）；
    - meta：扩展元信息（JSON 串，如备注/对接地址）。
    """
    src_id = f"ext-{uuid.uuid4().hex[:12]}"
    key = key or gen_key()
    ip_whitelist = ip_whitelist or []
    db.execute(
        """
        INSERT INTO external_sources
            (src_id, name, api_key, ip_whitelist, kind, meta,
             enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (src_id, name, key, ",".join(ip_whitelist), kind,
         meta or "{}", 1, _now(), _now()),
    )
    return {"src_id": src_id, "name": name, "api_key": key,
            "ip_whitelist": ip_whitelist, "kind": kind}


def get_source(name=None, src_id=None):
    """按名或 id 取外部源登记。"""
    if name:
        row = db.query_one("SELECT * FROM external_sources WHERE name=?", (name,))
    elif src_id:
        row = db.query_one("SELECT * FROM external_sources WHERE src_id=?", (src_id,))
    else:
        return None
    if not row:
        return None
    d = dict(row)
    d["ip_whitelist"] = [x for x in (d.get("ip_whitelist") or "").split(",") if x]
    return d


def list_sources(limit=200):
    rows = db.query("SELECT * FROM external_sources ORDER BY id ASC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["ip_whitelist"] = [x for x in (d.get("ip_whitelist") or "").split(",") if x]
        out.append(d)
    return out


def update_source(name, key=None, ip_whitelist=None, enabled=None):
    """更新外部源（换钥 / 改白名单 / 启停）。"""
    fields, params = [], []
    if key is not None:
        fields.append("api_key=?")
        params.append(key)
    if ip_whitelist is not None:
        fields.append("ip_whitelist=?")
        params.append(",".join(ip_whitelist))
    if enabled is not None:
        fields.append("enabled=?")
        params.append(1 if enabled else 0)
    if not fields:
        return False
    # 占位符顺序：SET 各字段(=?)... , updated_at=? , WHERE name=?
    # 参数顺序：各字段值 ... , now, name
    db.execute(
        f"UPDATE external_sources SET {', '.join(fields)}, updated_at=? "
        f"WHERE name=?",
        (*params, _now(), name),
    )
    return True


# ---- 认证 ----
def authenticate(name, api_key, client_ip):
    """外部源认证入口：校验「源存在 + 已启用 + 秘钥匹配 + IP 在白名单」。

    返回 (ok, reason, source)。所有结果都留痕 external_auth（审计）。
    """
    src = get_source(name)
    if not src:
        return _auth_deny(name, api_key, client_ip, "unknown_source", "外部源未登记")
    if not src.get("enabled"):
        return _auth_deny(name, api_key, client_ip, "disabled", "外部源已停用")
    if not _secure_compare(src["api_key"], api_key):
        return _auth_deny(name, api_key, client_ip, "bad_key", "秘钥不匹配")
    if not _is_in_whitelist(client_ip, src["ip_whitelist"]):
        return _auth_deny(name, api_key, client_ip, "ip_not_allowed",
                          f"来源 IP {client_ip} 不在白名单")
    _auth_allow(name, client_ip, src["src_id"])
    return (True, "pass", src)


def _auth_deny(name, api_key, client_ip, reason_code, reason):
    """认证失败：拦截 + 留痕审计。返回 (False, reason, None)。"""
    db.execute(
        """
        INSERT INTO external_auth
            (auth_id, source_name, client_ip, result, reason, api_key_masked,
             created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (f"au-{uuid.uuid4().hex[:12]}", name, client_ip, "deny", reason,
         _mask(api_key), _now()),
    )
    return (False, reason, None)


def _auth_allow(name, client_ip, src_id):
    """认证成功：留痕审计。"""
    db.execute(
        """
        INSERT INTO external_auth
            (auth_id, source_name, client_ip, result, reason, api_key_masked,
             created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (f"au-{uuid.uuid4().hex[:12]}", name, client_ip, "allow", "pass", "",
         _now()),
    )


def _mask(key):
    """秘钥打码后留痕（不落明文，安全红线）。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return key[:2] + "*" * (len(key) - 4) + key[-2:]


def audit(limit=200):
    """认证审计日志（供 Web 面板俯瞰：谁/何时/从哪 IP 打哪个 key）。"""
    rows = db.query("SELECT * FROM external_auth ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def overview():
    rows = db.query(
        "SELECT result, COUNT(*) AS n FROM external_auth GROUP BY result"
    )
    return {r["result"]: r["n"] for r in rows}
