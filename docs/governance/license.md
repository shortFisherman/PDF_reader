# 许可证与再分发核验基线

> 本文档是工程记录，**不是法律意见**。发布或部署前，应按实际组合方式单独核验。

## 1. 本项目许可证

- 本项目源代码以 **AGPL-3.0-only**（GNU Affero General Public License v3，仅此版本）授权。
- 仓库根目录 `LICENSE` 为标准完整 GNU AGPL v3 官方文本。来源直链：<https://www.gnu.org/licenses/agpl-3.0.txt>；核验日期 2026-08-30 下载 34523 字节，SHA-256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`。
- `pyproject.toml`（PEP 639：`license = "AGPL-3.0-only"`、`license-files = ["LICENSE"]`）、`package.json`、`package-lock.json` 根包、README 与 LICENSE 的 SPDX/声明一致为 `AGPL-3.0-only`。
- 采用依据：截至核验日期（2026-08-30），仓库没有相反授权事实（无其他 LICENSE/COPYING/NOTICE 或更具体的授权声明），故采用 `AGPL-3.0-only`。这不由本项目替任何第三方重新许可。

## 2. 固定翻译依赖的许可证核验（2026-08-30）

固定版本：`pdf2zh-next==2.9.0`、`babeldoc==0.6.2`（`requirements.lock` 锁定，本项不改依赖版本）。

### 2.1 pdf2zh-next 2.9.0

| 项目 | 核验结果 |
|---|---|
| 许可证标识 | AGPL-3.0（SPDX `License-Expression`） |
| 已安装 distribution metadata（本机 Python 3.12.8） | `License-Expression: AGPL-3.0`；Homepage 指向官方仓库 |
| PyPI project metadata | <https://pypi.org/pypi/pdf2zh-next/2.9.0/json>：`license_expression: AGPL-3.0` |
| wheel（bdist_wheel） | <https://files.pythonhosted.org/packages/58/15/660945bc602aa74e4630e101853ea2360dc0d4cd22d46296bc0e652a1b43/pdf2zh_next-2.9.0-py3-none-any.whl>（SHA-256 `4cf72454dbff21c6c35380aed5e3bfe29278f0fdbe87e83942adf89e33b37c68`）：METADATA `License-Expression: AGPL-3.0`、`License-File: LICENSE`；内嵌 `pdf2zh_next-2.9.0.dist-info/licenses/LICENSE` 34523 字节、SHA-256 `8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef` |
| GitHub 官方仓库 tag/LICENSE | <https://raw.githubusercontent.com/PDFMathTranslate-next/PDFMathTranslate-next/v2.9.0/LICENSE>：34523 字节、SHA-256 `8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef`，与 wheel 内嵌一致；官方仓库 <https://github.com/PDFMathTranslate-next/PDFMathTranslate-next> |

实际看到的标识/文件：wheel METADATA 的 `License-Expression: AGPL-3.0` 与 `License-File: LICENSE`；README 内 `<a href="./LICENSE">` 与 GitHub license 徽章链接；LICENSE 文本首两行为 `GNU AFFERO GENERAL PUBLIC LICENSE` / `Version 3, 19 November 2007`。

### 2.2 BabelDOC 0.6.2

| 项目 | 核验结果 |
|---|---|
| 许可证标识 | AGPL-3.0（SPDX `License-Expression`） |
| 已安装 distribution metadata（本机 Python 3.12.8） | `License-Expression: AGPL-3.0`；Homepage 指向官方仓库 |
| PyPI project metadata | <https://pypi.org/pypi/babeldoc/0.6.2/json>：`license_expression: AGPL-3.0` |
| wheel（bdist_wheel） | <https://files.pythonhosted.org/packages/a1/66/d4cd53a4f211fe76ba7f0663e4ba1ba79a41c06fdfbb2add6b1a189ec619/babeldoc-0.6.2-py3-none-any.whl>（SHA-256 `fa7252aa2b4b57c833334a0ab3f3466a1de8300953aaff86b53cd5df4b30db1e`）：METADATA `License-Expression: AGPL-3.0`、`License-File: LICENSE`；内嵌 `babeldoc-0.6.2.dist-info/licenses/LICENSE` 34519 字节、SHA-256 `afca41723b45e26069f68d485bf906a202f892f90c801d3052f8e6296bb41454` |
| GitHub 官方仓库 tag/LICENSE | <https://github.com/funstory-ai/BabelDOC/releases/tag/v0.6.2>（官方发布页）；<https://raw.githubusercontent.com/funstory-ai/BabelDOC/v0.6.2/LICENSE>：34519 字节、SHA-256 `afca41723b45e26069f68d485bf906a202f892f90c801d3052f8e6296bb41454`，与 wheel 内嵌一致；官方仓库 <https://github.com/funstory-ai/BabelDOC> |

实际看到的标识/文件：wheel METADATA 的 `License-Expression: AGPL-3.0` 与 `License-File: LICENSE`；README 内 GitHub license 徽章链接；LICENSE 文本首两行为 `GNU AFFERO GENERAL PUBLIC LICENSE` / `Version 3, 19 November 2007`。wheel 另含第三方组件许可证 `babeldoc/pdfminer/LICENSE`（MIT，Copyright Yusuke Shinyama，1092 字节）。

### 2.3 说明

- 上游发行物中的 AGPL v3 文本与 GNU 官方文本同为 AGPL v3，但字节不完全一致（pdf2zh-next 34523 字节、BabelDOC 34519 字节；GNU 官方 34523 字节，SHA-256 均不同）。本仓库 `LICENSE` 直接采用 GNU 官方文本，不以任何上游副本为准。
- 本仓库不替上游或第三方重新许可；pdf2zh-next、BabelDOC 及 BabelDOC 内嵌的第三方组件各自保留其 LICENSE 与版权声明。
- sdist 未逐字节核验（BabelDOC sdist 体积大、本次未下载完成）；已以 PyPI 官方 JSON、wheel METADATA/内嵌 LICENSE、GitHub tag/LICENSE 与已安装 distribution metadata 交叉核验。

## 3. 四种使用/分发场景

### 3.1 本地内部使用

本机单用户运行、不向他人分发源码或构建产物、不对外提供网络服务时，通常不产生再分发义务；但运行仍受本项目与各依赖自身许可证约束，本文档不对具体场景作法律判断。不要修改或移除依赖安装目录中的 LICENSE/COPYING 文件。

### 3.2 本项目源代码再分发

再分发本项目源代码时：

- 保留根目录 `LICENSE` 全文与版权/许可证声明；AGPL-3.0-only 要求以相同许可证再许可本项目代码，并提供许可证文本。
- 修改后分发仍须保留本声明与上游/第三方声明，并按 AGPL 处理修改说明与源码提供义务。
- 未获授权不得删除或替换上游/第三方许可证与版权声明。

### 3.3 与 pdf2zh-next/BabelDOC 的组合再分发或网络部署

- 本项目运行时与 AGPL-3.0 上游组合（导入、子进程调用、打包包含等实际组合方式）时，组合分发或网络部署可能触发 AGPL 义务，包括但不限于以 AGPL 再许可组合产物、向网络用户提供对应源码、保留版权与许可证声明、不得附加额外限制。
- 本文档**不声称**“只要 Python 依赖就自动必然构成衍生作品”：是否构成组合/衍生作品取决于实际组合方式、分发形态与部署方式，必须按具体场景单独核验。
- 发布或部署前应核对实际组合方式（导入关系、打包内容、运行调用链、是否整体分发），并咨询合格法律意见；本文档不能代替该核验。
- 网络交互场景（AGPL 第 13 节）尤其需要确认源码提供渠道与再许可安排。

### 3.4 上游/依赖许可证与本项目许可证的关系

- 本项目采用 AGPL-3.0-only，不改变上游/依赖自身许可证；上游与第三方组件各自保留许可与版权（例如 BabelDOC 内嵌 pdfminer 为 MIT）。
- 同属 AGPL 系列许可证不自动使组合整体复制为本项目的许可证声明；以实际再分发/部署场景与各组件声明为准。
- 上游版本或发行物变化时，按 [dependency-upgrade.md](dependency-upgrade.md) 的契约在升级时重新核验。

## 4. 发布/部署前核验清单（非法律意见）

- [ ] 确认实际组合与分发形态，逐项核对上游许可证文本与声明。
- [ ] 保留所有 LICENSE/COPYING/NOTICE 与版权行，不替第三方重新许可。
- [ ] 落实 AGPL 源码提供义务（含网络用户）的具体方案。
- [ ] 对构建产物（wheel/sdist/二进制/镜像等）做许可证扫描。
- [ ] 必要时咨询具备资质的法律顾问。
