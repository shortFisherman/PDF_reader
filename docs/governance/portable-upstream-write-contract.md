# Windows 便携版上游写入契约

> 适用基线：pdf2zh-next 2.9.0、BabelDOC 0.6.2、huggingface-hub 1.29.0、
> tiktoken 0.14.0。本文记录 P0-03 已核验的运行时写入来源；升级上述依赖前后必须运行
> `python scripts/upgrade_governance_gate.py`。

## 边界

便携服务的所有第三方模块都在子进程受控环境建立后才导入。顶层启动器保留真实
`HOME`、`USERPROFILE` 和系统临时目录，用于打开默认浏览器；服务子进程使用
`DATA_ROOT/home`、带归属标记的单次会话临时目录以及显式 Hugging Face 缓存变量。
这些变量只传给服务进程树，不写入用户或系统环境。

当前固定依赖没有 ModelScope、Torch 或 Transformers，因此不设置它们的缓存变量。
如果以后把这些包加入锁文件，应先审计该版本实际读取的公开配置，再扩展本表和契约测试。

## 写入来源—控制方式—目标目录

| 写入来源 | 求值时机 | 控制方式 | 便携目标（相对 `DATA_ROOT`） |
|---|---|---|---|
| BabelDOC 根缓存 | 导入 `babeldoc.const` 时 `Path.home()` | 导入前设置子进程 `HOME`/`USERPROFILE` | `home/.cache/babeldoc/` |
| BabelDOC 版面模型 | 首次模型校验/下载 | 根缓存的 `models` 子目录 | `home/.cache/babeldoc/models/` |
| BabelDOC 字体文件 | 首次字体校验/下载 | 根缓存的 `fonts` 子目录；只以文件路径嵌入 PDF | `home/.cache/babeldoc/fonts/` |
| BabelDOC CMap 与资源元数据 | 首次资源校验/下载 | 根缓存的 `cmap` 子目录；元数据在内存或资源文件中消费 | `home/.cache/babeldoc/cmap/` |
| BabelDOC/tiktoken 缓存 | 导入 `babeldoc.const` 时 | 导入前设置同值 `TIKTOKEN_CACHE_DIR`，上游随后固定为该目录 | `home/.cache/babeldoc/tiktoken/` |
| BabelDOC 翻译缓存 | 导入 translator cache 时初始化 SQLite | 虚拟 Home；项目当前 `ignore_cache=True`，但导入初始化仍受控 | `home/.cache/babeldoc/cache.v1.db`（含 SQLite sidecar） |
| pdf2zh-next 翻译缓存 | 导入 translator cache 时初始化 SQLite | 虚拟 Home；项目当前 `ignore_cache=True` | `home/.cache/pdf2zh_next/cache.v1.db`（含 SQLite sidecar） |
| pdf2zh-next 默认配置目录 | 导入 `pdf2zh_next.const` 时 `expanduser()` | 虚拟 Home | `home/.config/pdf2zh/` |
| Python/上游 `tempfile` | 运行期首次调用 | `TEMP`/`TMP`/`TMPDIR` 指向单次服务会话目录 | `temp/pdf-reader-service-*/` |
| Python 字节码 | 解释器导入期 | `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPYCACHEPREFIX` 防御性收口 | `pycache/`（正常便携服务不应产生） |
| huggingface-hub 1.29.0 | 该传递依赖被调用或导入常量时 | `HF_HOME`、`HUGGINGFACE_HUB_CACHE`、`HF_HUB_CACHE`、`HF_ASSETS_CACHE` | `upstream-cache/huggingface/` |

`DATA_ROOT/models/` 与 `DATA_ROOT/fonts/` 保留给未来由 PDF Reader 自己拥有、具有独立
manifest/迁移语义的资源。当前 BabelDOC 资源必须保持在其受控虚拟 Home 缓存中；项目不以
monkey patch、影子包、vendor 上游源码或目录链接改写上游常量。

## 临时目录生命周期

顶层启动器每次创建 `temp/pdf-reader-service-<随机值>/`，并写入
`.pdf-reader-service-temp`（类型、启动器 PID、创建时间）。服务及其上游子进程只看到该目录
作为系统 Temp。正常退出、启动失败或用户中断后，启动器只在路径仍是 `data/temp` 的直接
子目录、名称前缀正确、不是 symlink/junction 且标记有效时删除它。

下次启动只清理由本程序标记且其启动器 PID 已确认不存在的会话目录；未知、无标记、标记
损坏、链接目录或 PID 状态不确定的目录一律保留。模型/字体下载失败由 BabelDOC 对目标文件
做哈希校验并删除损坏文件；取消发生在写入前时不创建目标文件。无论成功、失败、取消或
崩溃，所有候选路径仍位于 `DATA_ROOT` 内。

## 字体边界

BabelDOC 0.6.2 下载普通字体文件后直接以文件路径用于 PDF 生成。当前项目与固定上游均不调用
Windows `AddFontResource*`、字体注册表、系统 Fonts 目录或安装器接口。便携版不安装系统或
用户字体；依赖升级若引入此类行为，契约扫描必须失败并在升级前重新设计。

## 自动验证

`tests/release/test_portable_processes.py` 在独立 Python 子进程中按真实导入顺序验证：

- 受控环境早于 pdf2zh-next/BabelDOC 导入；
- 固定上游的模型、字体、CMap、tiktoken、配置、翻译缓存与 `tempfile` 路径；
- 未安装依赖的缓存变量不会被无依据地注入；
- 服务临时目录的标记、正常清理和崩溃恢复边界；
- 项目及固定 BabelDOC 源码不包含 Windows 字体安装调用。

该文件已加入一键上游升级治理门。公网首次下载和最终 ZIP 的目录外写入审计分别在受控手工
验证和 P2-02 干净机发行验证中再次执行；它们不替代这里的离线源码契约。
