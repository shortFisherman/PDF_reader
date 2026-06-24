# Proposal: Split pdf_renderer.py

## Motivation

`pdf_renderer.py` 目前包含两个职责无关的函数：
- `render_page()` — PDF 页面渲染为 PNG 字节（供浏览器显示）
- `build_settings()` — 组装 pdf2zh-next 翻译参数（供翻译流程使用）

这两个函数共享一个文件仅因历史原因。按项目「高内聚、低耦合」原则应拆分。

## Goals

- 将 `build_settings()` 移到独立模块 `translation_settings.py`
- `pdf_renderer.py` 回归单一职责：只负责 PDF 页面渲染

## Scope

- 新增 `translation_settings.py`
- 修改 `pdf_renderer.py`（删除 `build_settings` 及其 import）
- 更新 `routes.py` 和 `tests/test_services.py` 的 import 路径
