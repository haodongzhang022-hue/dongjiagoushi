# -*- coding: utf-8 -*-
"""
StationAnchor · 站点锚定模型（M1-M3 · 云端-本地协同）
======================================================
对应 Issue #90「云端和本地协同时候的分工问题」中云端 @架构·总师 的
「地铁站点模型」M1-M3（cloud 侧待落地，本地先行实现可运行语义）：

  M1 station  ：站点登记。云端/本地各执一个「站点」（git 分支/tag 时间点），
                站点 = 一份可重放的版本基准（不漂移）。
  M2 anchor   ：版本锚定。把某时点的 commit/版本 锚定为协同基准，写锚点记录；
                锚点之后所有变更都相对该锚点计算，防止双方各自演进导致漂移。
  M3 replay   ：迁移重放。给定两个锚点（本地、云端）之间的变更序列，产出
                重放计划（rebase/merge 顺序），在一侧重放另一侧变更，保证一致。

M4 build-cache 联动：站点级构建缓存键（git tree hash → 缓存状态），
                复用 hybrid FingerprintCache，锚点变化即缓存失效。
M5 review-gate：评审闸门（≤5 轮熔断），配合 disposition 处置标签，
                超限强制合并确认（⏸CP3）。

与云端统一口径：锚点 = (git branch, git commit hash, timestamp)。
"""
import os
import time
import subprocess

# 站点锚点记录文件（与 quota/batch 同目录习惯）
ANCHOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".station_anchors.json")
# 评审轮次上限（M5 review-gate 熔断阈值）
DEFAULT_MAX_REVIEW_ROUNDS = 5

# 站点角色：cloud 云端 / local 本地（可扩展 phone/vm/sandbox）
STATION_ROLES = ("cloud", "local")


class StationAnchor(object):
    """站点锚定模型：登记站点 + 锚定版本 + 计算重放计划 + 缓存/评审联动。"""

    def __init__(self, anchor_file=ANCHOR_FILE,
                 max_review_rounds=DEFAULT_MAX_REVIEW_ROUNDS):
        self.anchor_file = anchor_file
        self.max_review_rounds = max_review_rounds

    # ---------- 锚点存取 ----------
    def _load(self):
        try:
            if os.path.exists(self.anchor_file):
                with open(self.anchor_file, "r", encoding="utf-8") as f:
                    d = json_load(f)
                    if isinstance(d, dict):
                        return d
        except Exception:  # noqa
            pass
        return {"stations": {}, "reviews": {}, "seq": 0}

    def _save(self, d):
        with open(self.anchor_file, "w", encoding="utf-8") as f:
            json_dump(d, f)

    # ---------- M1 station：站点登记 ----------
    def register_station(self, role, branch, commit, tag="", note=""):
        """登记一个站点（role ∈ cloud/local）。返回锚点记录。"""
        if role not in STATION_ROLES:
            role = "local"
        d = self._load()
        d["seq"] = d.get("seq", 0) + 1
        d["stations"][role] = {
            "role": role,
            "branch": branch,
            "commit": commit,
            "tag": tag,
            "ts": _ts_now(),
            "seq": d["seq"],
            "note": note,
        }
        self._save(d)
        return d["stations"][role]

    def get_station(self, role="local"):
        """读取某站点锚点；未登记返回 None。"""
        d = self._load()
        return d.get("stations", {}).get(role)

    def list_stations(self):
        """列出全部站点锚点。"""
        return self._load().get("stations", {})

    # ---------- M2 anchor：版本锚定 ----------
    def anchor(self, role="local", branch=None, commit=None, tag="", note=""):
        """锚定一个版本为协同基准（anti-drift）。

        不传 branch/commit 时自动探测当前 git 状态（HEAD commit + 当前分支）。
        写锚点记录，返回锚点 dict。
        """
        if not commit:
            git = self._git_info()
            branch = branch or git.get("branch", "")
            commit = commit or git.get("commit", "")
        rec = self.register_station(role, branch or "", commit or "",
                                    tag=tag, note=note)
        return {"role": role, "branch": rec["branch"], "commit": rec["commit"],
                "tag": rec.get("tag", ""), "ts": rec["ts"]}

    # ---------- M3 replay：迁移重放 ----------
    def replay_plan(self, from_role="cloud", to_role="local"):
        """计算从 from_role 站点到 to_role 站点的重放计划。

        返回结构：{base, target, status, steps, drift}。
          - base   : 目标站点（to_role）当前锚点 commit
          - target : 源站点（from_role）锚点 commit
          - status : in_sync / behind / ahead / drift
          - steps  : 重放步骤（需迁移的变更序列）
          - drift  : 两站点 commit 是否一致
        """
        src = self.get_station(from_role)
        dst = self.get_station(to_role)
        if not src or not dst:
            return {"status": "unregistered",
                    "reason": "缺少 %s/%s 站点锚点" % (from_role, to_role),
                    "steps": [], "drift": True}
        drift = src["commit"] != dst["commit"]
        if not drift:
            return {"base": dst["commit"], "target": src["commit"],
                    "status": "in_sync", "steps": [], "drift": False}
        # 有漂移：目标落后于源 → 需把源变更重放到目标
        steps = self._diff_steps(dst["commit"], src["commit"])
        if not steps:
            # git diff 为空（离线/伪造 commit/源落后）→ 用锚点顺序 seq 判方向：
            # 源站点锚定序列更新（seq 更大）→ 目标落后，需重放源变更。
            src_seq = src.get("seq", 0)
            dst_seq = dst.get("seq", 0)
            if src_seq > dst_seq:
                return {"base": dst["commit"], "target": src["commit"],
                        "status": "behind", "steps": [], "drift": True,
                        "note": "源站点锚点更新（seq=%d>%d，git diff 空按序判），"
                                "目标落后，需重放源变更" % (src_seq, dst_seq)}
            # 源落后或无法判定 → 目标领先，无需重放
            return {"base": dst["commit"], "target": src["commit"],
                    "status": "ahead", "steps": [], "drift": True,
                    "note": "目标站点领先源站点，无需重放"}
        return {"base": dst["commit"], "target": src["commit"],
                "status": "behind", "steps": steps, "drift": True}

    def _diff_steps(self, base_commit, target_commit):
        """用 git 计算 base→target 的提交序列（按时间序）。失败返回空。"""
        try:
            out = subprocess.check_output(
                ["git", "log", "--oneline", "--no-abbrev-commit",
                 "%s..%s" % (base_commit, target_commit)],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "replace").strip()
            if not out:
                return []
            return [line for line in out.splitlines() if line]
        except Exception:  # noqa
            return []

    def replay_apply(self, from_role="cloud", to_role="local", dry=True):
        """执行重放（默认演练）。真实模式下对 to_role 站点所在 git 做 rebase 到源。

        ⚠️ 真实模式会改 git 历史，默认 dry=True 只打印计划不执行。
        """
        plan = self.replay_plan(from_role, to_role)
        if plan.get("status") != "behind":
            return plan
        if dry:
            plan["applied"] = False
            plan["note"] = "dry-run 演练：未实际 rebase"
            return plan
        # 真实模式：把当前分支 rebase 到源 commit
        src = self.get_station(from_role)
        try:
            subprocess.check_call(
                ["git", "rebase", src["commit"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            plan["applied"] = True
        except Exception as e:  # noqa
            plan["applied"] = False
            plan["error"] = "rebase 失败: %s（可用 git rebase --abort 回滚）" % e
        return plan

    # ---------- M4 build-cache 联动 ----------
    def build_cache_key(self, role="local", suffix="tests"):
        """站点级构建缓存键：role + git tree hash（锚点 commit 的树）+ suffix。

        缓存键随锚点变化而变化 → 锚点更新即缓存失效，天然联动 FingerprintCache。
        """
        st = self.get_station(role)
        commit = (st or {}).get("commit", "")
        tree = self._tree_hash(commit)
        return "%s/%s/%s/%s" % (role, commit[:12], tree[:8], suffix)

    def _tree_hash(self, commit):
        """取某 commit 的 git tree hash（缓存失效依据）。失败返回 'unknown'。"""
        if not commit:
            return "unknown"
        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "%s^{tree}" % commit],
                stderr=subprocess.DEVNULL).decode("utf-8", "replace").strip()
            return out or "unknown"
        except Exception:  # noqa
            return "unknown"

    # ---------- M5 review-gate：评审闸门 ----------
    def review_round(self, role="local", verdict="fix_bug"):
        """记录一次评审轮次。超 max_review_rounds 即熔断 → 强制合并确认。

        返回 {rounds, max, fused, gate}：
          fused=True 表示该评审已熔断（需人类 ⏸CP3 拍板，不再无限循环）。
        """
        d = self._load()
        r = d["reviews"].setdefault(role, {"rounds": 0, "verdicts": []})
        r["rounds"] += 1
        r["verdicts"].append({"n": r["rounds"], "verdict": verdict,
                              "ts": _ts_now()})
        r["fused"] = r["rounds"] >= self.max_review_rounds
        self._save(d)
        return {
            "rounds": r["rounds"],
            "max": self.max_review_rounds,
            "fused": r["fused"],
            "gate": "human_cp3" if r["fused"] else "open",
        }

    def review_status(self, role="local"):
        """查询评审闸门状态。"""
        r = self._load().get("reviews", {}).get(role, {"rounds": 0, "fused": False})
        return {
            "role": role,
            "rounds": r.get("rounds", 0),
            "max": self.max_review_rounds,
            "fused": r.get("fused", False),
            "gate": "human_cp3" if r.get("fused", False) else "open",
        }

    def review_reset(self, role="local"):
        """评审通过后复位轮次。"""
        d = self._load()
        d["reviews"].pop(role, None)
        self._save(d)
        return self.review_status(role)

    # ---------- 工具 ----------
    def _git_info(self):
        """探测当前 git 分支 + HEAD commit。非 git 目录返回空。"""
        info = {"branch": "", "commit": ""}
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL).decode().strip()
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL).decode().strip()
            info = {"branch": branch, "commit": commit}
        except Exception:  # noqa
            pass
        return info


# ---------- 轻量 json 帮助（避免顶层 import 冲突） ----------
def json_load(fp):
    import json
    return json.load(fp)


def json_dump(d, fp):
    import json
    json.dump(d, fp, ensure_ascii=False, indent=2)


def _ts_now():
    """秒级 ISO 时间戳（站点锚定顺序判定用，同一秒内也需确定先后）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# 便捷单例
default_anchor = StationAnchor()
