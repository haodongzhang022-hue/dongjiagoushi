# @dongjiagoushi/dsh-adapter

架构师体系 ⇄ **DeepSeek Harness (dsh)** 适配插件（新版 `0.1.6-alpha.2` 兼容）。

> 完整说明见 [`../docs/DSH_ADAPTER.md`](../docs/DSH_ADAPTER.md)；决策见
> [`../docs/adr/0014-dsh-adapter-new-version.md`](../docs/adr/0014-dsh-adapter-new-version.md)。

## 快速使用

```bash
# 1) 构建产物（新版 loader 只 import lib/index.js）
node dsh-adapter/scripts/build.mjs
# 2) 装配进 profile（组合包机制）
dsh plugin --profile headless add /path/to/dongjiagoushi/dsh-adapter
# 3) 核验
dsh --profile headless --dump-config | grep dongjiagoushi-dsh-adapter
```

## 测试

```bash
bash local-agent/tests/test_dsh_adapter.sh     # 18 组信号灯
```

## 关键点

- **版本闸门**：加载即 `checkVersion()`，缺必需 API 面（profile-bundle / cordis-all-plugin /
  defineTool）显式失败，不静默。
- **只桥不重写**：工具经子进程桥转发到 `local-agent/` 既有 Python 引擎。
- **只 import 构建产物**：新版 loader 硬约束；附零依赖构建脚本。
