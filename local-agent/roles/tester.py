# -*- coding: utf-8 -*-
"""架构·测试：测试矩阵/信号灯 + 接手评审转交后继续开发推进。

与 settings.yml 同源。本角色除给出测试矩阵/信号灯外，**收到评审转交
（`@org/repo(架构·测试)` + `[触发:架构·测试]`）必须回执 [接单] 接手**，
并继续推进到结果——不只描述，而是真实开工 + 进度尺推进。
"""
from .base import BaseRole


class TesterRole(BaseRole):
    name = "架构·测试"

    SYSTEM_PROMPT = """
你是「架构·测试」，本团队质量验收角色。接手必交：
- 测试矩阵（功能 / 性能 / 安全 / 联调 / E2E）
- 缺陷分级：🔴P0 / 🟠P1 / 🟡P2
- 信号灯：🟢通过 / 🟡有条件 / 🔴阻塞

协作纪律：
- 信号灯🟢才放行；🔴阻塞阻断并说明原因；🔴未清零不给🟢。
- **收到评审转交（完整 `@org/repo(架构·测试)` + `[触发:架构·测试]`）必须回执
  `[接单]` 接手**，并用 `ack_wake`/`start_work`/`track_progress` 真实开工推进
  到结果——不得只描述"收到，待测试"而不真正接手推进。

触达协议：显式[触发:架构·测试]/语义命中"测试/验收/联调/信号灯/阻塞"即进入本角色；
🔴阻塞必须打回（revert_to develop），清零复测才放行。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "测试矩阵(test_matrix)",
                "缺陷分级(bug_severity: 🔴/🟠/🟡)",
                "信号灯(signal: 🟢/🟡/🔴)",
                "**接手评审转交后继续开发(take_over_and_develop: [接单]+开工+进度尺推进)**",
            ],
        }

    # ------------------------------------------------------------
    # 接手评审转交 → 继续开发推进（解决"评审转交后测试没真接手"）
    # ------------------------------------------------------------
    def take_over_and_develop(self, task_key, agent_id="", test_scope="",
                              goal_total=10, current=0, issue_ref="",
                              note="[接单] 已接管评审转交，开始验收推进"):
        """评审转交后**接手继续开发**：回执 [接单] + 开工 + 进度尺推进。

        三步闭环（不只描述）：
          1. `ack_wake` 回执接管（标记路由真实唤醒成立）；
          2. `start_work` 正式开工（in_progress）；
          3. `track_progress` 写进度尺（goal_meters，供哨兵收敛判定）。
        返回结构化结果供留痕核验；signal 由测试实际执行后回填。
        """
        agent_id = agent_id or self.name
        ack = self.ack_wake(task_key, role=self.name, note=note)
        start = self.start_work(task_key, role=self.name, note="已开工，进入验收推进")
        progress = self.track_progress(
            task_key, agent_id, target="验收通过并交付", goal_total=goal_total,
            current=current, note=note, role=self.name)

        relay = ("@dongdongxiaozu/dongjiagoushi(架构·测试) "
                 "[触发:架构·测试] 已接单")
        return {
            "accepted": True,
            "ack": ack,
            "started": start.get("status") or start.get("state", "in_progress"),
            "progress": progress,
            "task_key": task_key,
            "issue_ref": issue_ref,
            "test_scope": test_scope,
            "relay_receipt": relay,
            "next_step": ("继续执行测试矩阵 → 给信号灯(🟢/🟡/🔴) → "
                          "🟢放行合并/🔴[回转]退回开发，推进到结果"),
        }
