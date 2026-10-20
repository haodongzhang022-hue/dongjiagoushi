# ADR-0015 降级链逐档绑定 + 降级显性可见

- 状态：Accepted
- 日期：2026-10-20
- 关联：Issue #192（承接 #182 审查发现的真 bug）、module `model-routing`

## 背景

`local-agent/llm/openai_compat.py` 构造多渠道 callers 时写成：

```python
callers = {m: (lambda sp, ui, **k: self._call_model(m, sp, ui, **k)) for m in chain}
```

lambda 捕获的是**推导式的循环变量 `m`**，循环结束后所有档的 caller 都指向链尾模型。
实测（main `5b5ba7c`）：

```
实际调用: ['glm-5.3-flash', 'glm-5.3-flash', 'glm-5.3-flash']
应当调用: ['deepseek-v4.1-flash', 'codebuddy', 'glm-5.3-flash']
```

后果有两层：

1. **三级降级链形同虚设**——主通道、二选通道从来没被真正试过，所有请求都发往链尾；
2. **伪装成"每档都试过了"**——`route_call` 的 attempts 里记着三次失败，看起来降级流程正常运转。

而 `engine.py` 全程没有 `degraded / fallback_from` 字段，上层完全看不到"这一轮到底换了模型没有"，
与仓库「不静默失败」规则正好相反。

## 决策

1. **逐档绑定闭包变量**：`lambda sp, ui, model=ch, **k: self._call_model(model, ...)`，
   默认参数在定义时求值，每档锁定自己的模型名。
2. **降级显性化**：`call()` 读 `route_call` 结果的 `attempts`，非空即发生降级 →
   写 `backend.last_degraded`（`from_model / used_model / attempts`）+ 记一条 warning；
   主档直通时 `last_degraded=None`。全链耗尽时同样落 `last_degraded` 再抛异常，不静默返回。
3. **信号灯锁死写法**：`test_model_routing.sh` ⑬ 用假后端真跑一遍 `call()` 验逐档顺序，
   ⑭ 源码级断言禁止退回"闭包捕获循环变量"的写法——两者缺一，这个 bug 就能悄悄回来。

## 为什么不用 `functools.partial`

`partial` 需要 `_call_model(model, sp, ui, **kw)` 的参数顺序与 `call_with_chain` 注入方式
严格对齐，可读性更差；默认参数绑定是这类问题的标准修法，且第 ⑭ 组信号灯能直接机器识别写法。

## 影响

- 只动 `llm/openai_compat.py` 一个模块 + 它自己的信号灯，无跨模块改动；
- 对"主档通"的常规路径零行为变化（仍然只调一次）；
- 对"主档不通"的路径，行为从「错发链尾」变为「按链序逐档真试」，恢复降级链本来的语义。
