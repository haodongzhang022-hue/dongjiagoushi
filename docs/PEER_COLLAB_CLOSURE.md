# Peer Collab 收尾闭环（同岗协作 · 会诊→审核者前置→人类）

> 对应 Issue #31「层间协作」缺漏 G1~G4 的收尾闭环实现。
> 让"同岗位多 agent 专家会诊解决不了"自动进入「审核者前置助手 → 人类拍板」，
> 能多自动一环就多自动一环，直到**功能验证通过**。

## 一、背景：peer collab 已实现，但收尾链路缺可执行引擎

`local-agent/collab/peer.py` 五支柱（cohort 编队 / 触发门控 / 专家会诊 / 动态扩容 /
自动分形）已落地并接入 DAG，7 项测试全绿。但规则层声明的收尾链路——
**"会诊解决不了怎么办"**——此前没有可执行引擎，只有文字/骨架：

| 缺漏 | 规则层声明 | 修复前 | 修复后（本模块） |
|------|-----------|--------|------------------|
| **G1 会诊升级链** | 会诊未收敛 → 审核者前置助手 L1→L2→L3 → 人类 | `expert_consult` 返回未收敛后**无消费方** | `precursor.py` + `closure.py` 自动进入升级链 |
| **G2 哨兵收敛监控** | 哨兵对同岗位协作组做收敛监控 | peer/orchestrator 未接 sentinel | `sentinel/peer_guard.py` 对 cohort 量化收敛监控 |
| **G3 会诊结论消费落地** | 会诊结论应驱动改道/补位/升级/交人 | 一次性返回，未落库未消费 | `decisions.py` 决策持久化 + 动作消费 |
| **G4 结果前置·人类拍板** | 决策点叫人类拍板、非事后背锅、CP 留痕 | 无承接 | `human_gate.py` 决策点打开人类闸门 + CP 留痕 |

## 二、模块拓扑（E1~E4 + 一编排）

```
peer.expert_consult(cohort, problem)
   ├─ resolved=True（功能验证通过）→ 放行 ✅
   └─ resolved=False（未收敛）→ closure.run() 收尾闭环
         ├─ E3 decisions.record_decision（决策落库 + enqueue 升级动作）
         ├─ E1 precursor.run（审核者前置助手）
         │     ├─ L1 内部分支：①合并保留·分场景 ②加约束 ③换道 ④补集
         │     ├─ L2 外部探索：⑤ 搜开源/插件/skill/论文现成方案
         │     │     ├─ 命中且负面小/零成本/零安全风险 → 自决采用 adopt ✅
         │     │     └─ 命中但需担责 / 未命中 → 进入 L3
         │     └─ L3 结果前置 → E4 human_gate 交人类拍板
         ├─ E2 peer_guard.guard_track（对 cohort 写收敛刻度 + 命中按协议打断/上报）
         └─ E3 decisions.consume_action（驱动改道/补位/升级/交人真正执行）
```

**触发硬约束**：本闭环**只在功能实现不了时才接入**；前置（单兵 → 补位 → 专家会诊）
一个都不能丢，缺前置直接触发 = 错误（`closure.run` 对 `consult_result=None` 报错）。

## 三、四模块接口契约

### E3 `collab/decisions.py` — 决策落库 + 动作消费
| 函数 | 职责 |
|------|------|
| `record_decision(...)` | 持久化一次决策（archives 表 kind='decision'），可回溯 |
| `list_decisions(task_id/stage)` | 审计/俯瞰 |
| `enqueue_action / pending_actions / consume_action` | 待消费动作队列（改道/补位/升级/交人/自决） |
| `apply_action(action, peer, cohort_id, problem)` | 把动作落地为 peer 引擎下一步（投递改道/补位横向消息） |

### E1 `collab/precursor.py` — 审核者前置助手
| 函数 | 层 | 职责 |
|------|----|------|
| `l1_explore(...)` | L1 | 把 ①合并保留 ②加约束 ③换道 ④补集 四内部分支全摊开 |
| `l2_explore(...)` | L2 | 开放探索型：外部搜公开最优解，判定 self_decidable |
| `l3_human(...)` | L3 | 结果前置：带问题+探索素材包+折中选项交人类拍板 |
| `run(...)` | 全 | 单次决策补全 L1→L2→L3，输出 outcome/decision |

### E4 `collab/human_gate.py` — 结果前置·人类拍板
| 函数 | 职责 |
|------|------|
| `open_gate(...)` | 决策点打开人类闸门（风险点显式列清 + CP 留痕） |
| `confirm_gate(gate_id, by)` | 人类确认放行（`by` 为空禁止放行——禁代替确认） |
| `reject_gate(...)` | 人类否决（被打回/终止该路线） |
| `ensure_human_gate(...)` | 幂等：同问题已 open 复用，不重复打扰人类 |

### E2 `sentinel/peer_guard.py` — 哨兵同岗收敛监控
| 函数 | 职责 |
|------|------|
| `guard_track(cohort_id, task, problem, goal_total, current)` | 对 cohort 写收敛刻度 + 立即判定 |
| `guard_handle(...)` | track + 按命中级别执行 interrupt/escalate 协议 |
| `cohort_meter_summary(cohort_id)` | 同岗协作组收敛俯视图 |

## 四、判定口径（对齐用户确立口径）

- **以「功能验证是否通过」为准，不以"做了判断"当终局**：
  决策选择方案后，判定标准是方案实施是否足够解决了分配的任务/功能；
- **结果前置·非事后背锅**：有负面责任需要决策的那一刻，就把人类叫出来拍板，
  信息必须足够明确（风险点显式列清），人类自己选、自己接受；
- **AI 判断"没办法"不等于真没路**：换个问法/问一下可能不一样；若补充信息后
  仍无更明显的好方案但属**必要成本**，可做但**必须人类确认**；
- **功能未达成链路**（缺前置不丢）：先到小组长看有无其他实现路线 → 小组长解决不了
  才到总师判断架构调整 → 不适合调整则折中/取舍 → 仍解决不掉则询问人类。

## 五、测试

`local-agent/tests/test_peer_closure.sh`（7 项）：
1. 会诊收敛 → 直接放行，不进收尾闭环
2. 缺前置直接触发 → 报错（前置硬约束）
3. E3 决策落库 + 动作消费
4. E1 L1 四分支 + L2 自决 + L3 交人
5. E4 人类拍板结果前置 + CP 留痕 + 禁代替确认
6. E2 哨兵同岗收敛监控
7. closure 全链路编排（run_consult_chain）

## 六、给架构·经理的理解与安排

任务分级后的同岗协作，其**收尾链路现已可自动闭环**：

1. **默认单兵 → 差异化补位 → 专家会诊**（已有，peer.py）；
2. **会诊未收敛 → 自动进入收尾闭环**（本次补齐）：`closure.run_consult_chain` 自动
   走「审核者前置助手 L1→L2→L3 → 人类拍板」，能自决就自决、需担责就结果前置交人；
3. **经理/小组长编排**：用 `decisions.pending_actions` 看有哪些决策动作待消费，
   用 `human_gate.list_gates(status='open')` 看哪些决策点在等人类；
4. **哨兵**：`sentinel.peer_guard.peer_guard_overview()` 看同岗协作组收敛健康度。

**开发分工建议**：本闭环四个模块 + 一编排已全部落地为可运行引擎并通过测试；
如需继续加固，可由经理按功能域（决策/前置/人类闸门/哨兵监控）分派，base 一律 `main`，
自含测试文档。
