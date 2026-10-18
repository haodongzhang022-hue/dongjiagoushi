# dsh_adapter（Python 侧）

dsh 版本兼容自检的 **Python 侧事实源**，与 `dsh-adapter/src/compat.ts`（TS 侧）同源。

```bash
python3 -m dsh_adapter.compat check 0.1.6-alpha.2   # → ok
python3 -m dsh_adapter.compat matrix                # → 完整兼容矩阵
```

模块说明见 `docs/DSH_ADAPTER.md`，决策见 `docs/adr/0014-dsh-adapter-new-version.md`。
