## Why

项目根目录堆积了调研报告、开发指南、术语表等文件，与源码混在一起，不符合工程规范。

## What Changes

- 将 3 个 markdown 报告/指南文件移入 `docs/` 目录
- 将 `glossary.csv` 术语表移入 `docs/` 并更新 `config.py` 中的路径引用
- 根目录仅保留源码、配置和标准工程文件

## Capabilities

_无新能力，纯文件整理_

## Impact

- 4 个文件移动
- `config.py` 一行路径修改
