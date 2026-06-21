## 1. 等价回归基线

- [ ] 1.1 在 `tests/test_engine_registry.py` 编写测试：对现有 10 引擎，断言 `resolve_engine(provider)` 与 `build_engine_kwargs` 产出与现状 `PROVIDER_MAP`+`FIELD_MAP` 完全一致（捕获当前行为为基线）
- [ ] 1.2 运行确认基线在现状代码上通过

## 2. 实现 EngineSpec 注册表

- [ ] 2.1 在 `config.py` 定义 `EngineSpec` dataclass（provider/settings_cls/field_map）与 `ENGINE_REGISTRY: list[EngineSpec]`
- [ ] 2.2 从现有 `PROVIDER_MAP`+`FIELD_MAP` 机械推导 10 个引擎的 `EngineSpec`，逐引擎对照字段映射
- [ ] 2.3 派生 `PROVIDER_INDEX: dict[str, EngineSpec]` 供快速查找
- [ ] 2.4 运行等价回归测试（步骤1.1）通过

## 3. 重构 services.build_engine_kwargs

- [ ] 3.1 重写 `services.resolve_engine`：从 `PROVIDER_INDEX` 查找，未命中回退 `OpenAICompatibleSettings`
- [ ] 3.2 重写 `services.build_engine_kwargs`：接收 `EngineSpec`，遍历 `spec.field_map` 从 config 读值构建 kwargs，必填校验与可选警告保持现状语义
- [ ] 3.3 删除 `config.py` 的 `PROVIDER_MAP` 与 `FIELD_MAP`（已被注册表取代）
- [ ] 3.4 运行 `tests/test_services.py` 与等价回归测试通过

## 4. 扩展性验证

- [ ] 4.1 在 `tests/test_engine_registry.py` 编写测试：声明一个"假引擎" `EngineSpec`（mock Settings class），仅加 1 处声明，断言 `resolve_engine("fake")` 与 `build_engine_kwargs` 正确工作
- [ ] 4.2 运行扩展性测试通过

## 5. 全量回归与 lint

- [ ] 5.1 运行 `pytest tests/ -v`，全部测试通过
- [ ] 5.2 运行 `ruff check`，零错误
