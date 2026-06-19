# Brainstorm Summary

- Change: multi-model-provider
- Date: 2026-06-19

## Confirmed Technical Approach

- **引擎路由**: 查表法 — `PROVIDER_MAP` 字典（10 个专用引擎 + `OpenAICompatibleSettings` 通用兜底）
- **字段映射**: 白名单映射表 — 统一配置字段名通过 `FIELD_MAP` 按引擎类名映射到实际字段
- **配置结构**: 单一 `[model]` 段，字段: `provider` / `api_key` / `model` / `base_url`（必填）+ 可选高级参数
- **错误处理**: 不支持字段打印 warning 日志，缺失 api_key 启动时报错，未知 provider 走兜底
- **不做向后兼容**: 旧 `[deepseek]` 段和 `DEEPSEEK_API_KEY` 环境变量不保留兼容

## Key Trade-offs and Risks

- 白名单映射表维护成本略高，但精确可控
- 专用引擎享受特有功能，代价是 base_url 不能随意改（引擎内部 hardcoded）
- 不支持字段打印 warning，用户能感知配置无效

## Testing Strategy

- 更新现有 test_build_settings_* 测试
- 新增: DeepSeek（含 thinking_mode）、OpenAICompatible、未知 provider 兜底、字段忽略 + warning、缺少 api_key 报错

## Spec Patches

无
