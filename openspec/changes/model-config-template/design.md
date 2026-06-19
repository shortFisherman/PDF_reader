# 设计：模型配置模板

## 实现方案

创建 `config.example.toml` 作为配置文件模板，包含：

- `[pdf_reader]` — PDF 阅读器设置（DPI、缓存目录）
- `[deepseek]` — 模型配置（**核心改进**：添加详细中文注释解释 api_key、model、base_url 的含义和获取方式）
- `[translation]` — 翻译设置（语言对、QPS）
- `[server]` — 服务器设置

更新 `README.md` 快速开始章节：
- 在"安装"步骤后增加 `cp config.example.toml config.toml` 引导
- 提示用户编辑 `config.toml` 填入自己的 API Key

## 影响

- 无代码变更
- 无接口变更
- 无架构变更
