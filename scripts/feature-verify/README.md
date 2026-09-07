# scripts/feature-verify —— 功能级校验脚本库（Test-First 证据库）

> 分层层级：`tests/test_*.sh` 保框架畅通 → `feature-verify/*.sh` 保**具体目标功能
> 按可感知语义真正做完** → 崩了跑 `feature-regress.sh` 定位坏功能 → `review_metrics`
> 分档量化度量。

## 这是什么
每个**目标功能**在开发前先写一份**机器可判**的校验脚本（Test-First）；一个 PR 对应
一份。脚本跑不过 = 功能没做完 = 合并闸门标 `blocked_on: feature_unverified`。

脚本不删——它就是**功能支撑证据档案库**，随模块版本线留痕，供回归诊断复现。

## 目录约定
```
scripts/feature-verify/
  README.md                    # 本说明
  _templates/verify.template.sh # 新功能校验脚本骨架（复制改名）
  <module>/<功能名>.sh          # 一处一功能，module=实现域，功能名可感知
```

## 五要素（每份脚本头部必须写清，机器可读）
1. **Given**   前提 / 前置（需要什么才能跑）
2. **When**    触发（实际执行什么动作）
3. **Then**    断言（按可感知语义判"功能是否完成"的机器判据）
4. **Evidence** 可核验产物（跑完落到哪个可 grep/可查的语义产物）
5. **Why 功能级** 说明为何纯断言/通畅抓不到（本脚本的增值点）

## 写脚本铁律
- **Test-First**：先写本脚本，再写实现。
- **一 PR 一脚本**：本 PR 的目标功能，对应本 PR 引入的 `<module>/<功能名>.sh`。
- **跑不过 = 没做完**：脚本红 → 不许标"我完成了"，须改到绿或打回重做。
- **不越层**：不替代 `test_*.sh`（保机制畅通）与 `review_metrics`（分档量化），互补。
- **可离线跑**：不依赖 cnb CLI 的能力尽量离线断言；依赖平台链路的按
  `test_functional_links.sh` 模式做 python/环境守卫优雅跳过，留本地/验收真跑。

## 常用命令
```bash
bash scripts/feature-verify.sh --all            # 全量回归
bash scripts/feature-verify.sh --list           # 证据库盘点
bash scripts/feature-verify.sh --changed        # 按变更自动选测
bash scripts/feature-regress.sh                 # 回归诊断（同 --all）
```
