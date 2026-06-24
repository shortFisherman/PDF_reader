# Tasks: defer-config-validation

## 1. config.py 改�?
- [x] 1.1 修改 `config.py:20` �?`CONFIG` 加载：`config.toml` 不存在时 `CONFIG = {}`（容错，不抛错）
- [x] 1.2 移除 `config.py:36-39` 导入期对 `MODEL_API_KEY`/`MODEL` �?`raise` 校验
- [x] 1.3 新增内部 `_validate_required_config()` 函数，缺�?哨兵时抛与原文案一致的 `ValueError`（保留中�?"请设�?model.api_key 或环境变�?MODEL_API_KEY" / "请设�?model.model"�?- [x] 1.4 确认 `DPI`/`CACHE_DIR` 等必键在缺失时的处理：维持现状或补明确报错，�?design 决策落地

## 2. 消费期校验接�?
- [x] 2.1 �?`engine_resolver.resolve_engine` 入口调用 `_validate_required_config()`（解析引擎前�?- [x] 2.2 确认 `translation_settings.build_settings` 经由 `resolve_engine` 自动覆盖校验，无需重复触发

## 3. 测试

- [x] 3.1 新增测试：无 `config.toml` �?`import config` 成功�?`CONFIG == {}`
- [x] 3.2 新增测试：`MODEL` 缺失�?`resolve_engine` �?"请设�?model.model"
- [x] 3.3 新增测试：`MODEL_API_KEY` 缺失/哨兵�?`resolve_engine` �?"请设�?model.api_key 或环境变�?MODEL_API_KEY"
- [x] 3.4 新增测试：已正确配置时行为不变（消费点触发同等校验）
- [x] 3.5 调整 `tests/conftest.py` `mock_config` �?fixture，确保无 `config.toml` 依赖
- [x] 3.6 运行 `ruff check .` �?`pytest -q`，确�?107+ 测试全过、lint 全过

## 4. 验证

- [x] 4.1 手动验证：在�?`config.toml` 环境下整链路翻译功能正常
- [x] 4.2 手动验证：在�?`config.toml` 环境�?`python -c "import config"` 不抛�?- [x] 4.3 交叉验证此变更为 `add-ci-and-lint-cleanup` 的前置依赖不再阻�