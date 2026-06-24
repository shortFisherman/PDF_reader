# Brainstorm Summary

- Change: defer-config-validation
- Date: 2026-06-24

## Confirmed Technical Approach

将所有 `config.py` 中的 `CONFIG[key]` 字典硬访问改为 `CONFIG.get(key, defaults)` 安全访问，并在 `engine_resolver.resolve_engine` 入口执行延迟的 `_validate_required_config()` 校验。具体：

- `CONFIG["model"]` → `CONFIG.get("model", {})`，嵌套字段逐层 `.get`
- 删除 `config.py:36-39` 两个导入期 `raise ValueError`
- 新增 `_validate_required_config()` 放在 `config.py`，由 `resolve_engine` 调用
- 默认值：DPI=200, CACHE_DIR=cache, lang_in=en, lang_out=zh, provider=openai_compatible, MODEL=""
- `TRANSLATION_LANG_IN/OUT` 也改为安全访问（不然 CI 也会 KeyError）

## Key Trade-offs and Risks

- 默认值在无配置下可能不符合预期（如 lang_in/lang_out），但 CI 只需导入成功，翻译才需校验
- 延迟校验的错误晚于导入期暴露——通过在消费点报原中文文案控制
- _resolve_debug() 已用 .get 安全访问，无需改动

## Testing Strategy

新增 4 个测试：无 config.toml 导入成功、MODEL 缺失报错、API key 哨兵报错、正确配置行为不变。调整 conftest.mock_config 确保 monkeypatch 在无 config.toml 下也生效。确认 107 已有测试全过。

## Spec Patches

无（delta spec 已在 open 阶段写入，无需修改）