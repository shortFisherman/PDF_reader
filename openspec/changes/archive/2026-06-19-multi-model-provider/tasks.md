## 1. 配置层重构

- [x] 1.1 重写 `config.toml`：`[deepseek]` → `[model]`，字段改为 `provider` / `api_key` / `model` / `base_url` + 可选高级选项
- [x] 1.2 重写 `config.py`：去掉 DeepSeek 专用常量，新增 `MODEL_PROVIDER` / `MODEL_API_KEY` / `MODEL` / `MODEL_BASE_URL` 等统一配置项，以及 `PROVIDER_MAP` 引擎路由表和 `FIELD_MAP` 字段映射表

## 2. 引擎路由实现

- [x] 2.1 重写 `services.py` 中 `build_settings`：根据 provider 动态选择引擎类，通过字段映射表将统一配置字段映射到引擎实例化参数，不存在的字段静默跳过
- [x] 2.2 环境变量：使用 `MODEL_API_KEY` 环境变量覆盖，`DEEPSEEK_API_KEY` 不再支持（用户确认无需向后兼容）

## 3. 文档与模板

- [x] 3.1 重写 `config.example.toml`：列出所有支持 provider 的可选值和示例，标注每个高级参数的支持范围（哪些引擎可用）
- [x] 3.2 更新 `README.md` 配置章节：说明多 provider 切换方式，标注 `[deepseek]` → `[model]` 迁移步骤

## 4. 测试

- [x] 4.1 更新 `tests/test_services.py` 现有测试适配新配置结构
- [x] 4.2 新增测试：DeepSeek 引擎（含 thinking_mode）、OpenAICompatible 引擎、未知 provider 默认兜底、不支持的字段静默忽略
