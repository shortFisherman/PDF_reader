"""发行态错误展示与安全诊断（P1-04，只依赖标准库）。

这个模块可以像启动器一样在导入任何应用/上游代码之前导入，因此不导入 Flask、
pdf2zh-next 或 BabelDOC。它固定三条边界：

* 稳定错误码到用户可读文案的唯一目录：启动器、服务就绪描述符与以后的用户界面共用
  同一份文案；未知码也必须落到安全兜底，新增错误码必须同时补文案。
* 错误窗口固定提供“复制诊断信息 / 打开日志目录 / 退出”，可恢复错误额外给出入口
  （打开配置目录、打开程序目录或重试启动）；窗口不显示原始异常文本。
* 诊断文本只包含允许的日志与版本信息，并在生成前脱敏：API Key、Bearer token、
  控制/健康令牌、Prompt、PDF 正文与用户名绝对路径都不得出现。
"""

from __future__ import annotations

import logging
import os
import platform
import re
import tempfile
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ERROR_WINDOW_TITLE = "PDF Reader 启动失败"
COPY_DIAGNOSTICS_LABEL = "复制诊断信息"
OPEN_LOGS_LABEL = "打开日志目录"
QUIT_LABEL = "退出"
RETRY_LABEL = "重试启动"
OPEN_CONFIG_LABEL = "打开配置目录"
OPEN_PROGRAM_LABEL = "打开程序目录"
DIAGNOSTICS_HEADER = "PDF Reader 便携版诊断信息（可安全分享）"
DEFAULT_LOG_RELATIVE = "data/logs/launcher.log"
MAX_DIAGNOSTIC_DETAIL_CHARS = 600
MAX_DIAGNOSTIC_TEXT_CHARS = 4000

ACTION_COPY_DIAGNOSTICS = "copy_diagnostics"
ACTION_OPEN_LOGS = "open_logs"
ACTION_OPEN_CONFIG_DIR = "open_config_dir"
ACTION_OPEN_PROGRAM_DIR = "open_program_dir"
ACTION_RETRY = "retry"
ACTION_QUIT = "quit"

RECOVERY_ACTIONS = frozenset({ACTION_OPEN_LOGS, ACTION_OPEN_CONFIG_DIR, ACTION_OPEN_PROGRAM_DIR, ACTION_RETRY})
RECOVERY_LABELS = {
    ACTION_OPEN_LOGS: OPEN_LOGS_LABEL,
    ACTION_OPEN_CONFIG_DIR: OPEN_CONFIG_LABEL,
    ACTION_OPEN_PROGRAM_DIR: OPEN_PROGRAM_LABEL,
    ACTION_RETRY: RETRY_LABEL,
}

logger = logging.getLogger("pdf_reader.launcher")

_GUIDE_LOGS = "请点击“复制诊断信息”，并把 data/logs 中的日志一并提供给维护者，以便定位问题。"


@dataclass(frozen=True, slots=True)
class ErrorPresentation:
    """一个稳定错误码的用户可读文案与恢复入口。"""

    code: str
    title: str
    summary: str
    guidance: str
    recovery: str | None = None

    @property
    def recoverable(self) -> bool:
        return self.recovery is not None


def _entry(
    code: str,
    title: str,
    summary: str,
    guidance: str,
    recovery: str | None = None,
) -> ErrorPresentation:
    return ErrorPresentation(code=code, title=title, summary=summary, guidance=guidance, recovery=recovery)


_CATALOG_ENTRIES: tuple[ErrorPresentation, ...] = (
    # === 便携目录与写入边界 ===
    _entry(
        "portable_layout_unavailable",
        "无法准备便携目录",
        "PDF Reader 无法从程序所在位置建立 data 目录。",
        "请确认程序是从压缩包完整解压出来的，并放在当前用户可写的目录（如桌面或文档）。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_not_writable",
        "便携目录不可写",
        "PDF Reader 需要在程序所在目录下保存配置和缓存，但当前目录不可写。",
        "请把整个 PDF Reader 文件夹移动到当前用户可写的位置后重新双击启动；程序不会改用系统其他目录。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_directory_unavailable",
        "无法创建便携数据目录",
        "PDF Reader 无法在程序所在目录下创建 data 子目录。",
        "请确认文件夹没有被只读属性、权限或安全软件阻止，然后重新双击启动。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_root_missing",
        "缺少便携根目录",
        "启动器无法从程序位置确定便携根目录。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_resource_outside_root",
        "程序资源位置异常",
        "便携程序的资源目录不在程序文件夹内。",
        "请重新解压完整的发行包后启动，不要单独移动 app 目录。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_outside_root",
        "数据目录位置异常",
        "便携数据目录不在程序文件夹内，可能存在目录链接或路径逃逸。",
        "请重新解压发行包；如果 data 目录是链接或 junction，请先移除它再启动。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "path_outside_data_root",
        "写入路径越界",
        "PDF Reader 拒绝把数据写到便携目录之外。",
        "请确认没有把 data 目录替换成指向其他位置的链接或 junction。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_unavailable",
        "便携数据不可用",
        "PDF Reader 无法读取或准备便携数据目录。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    # === 单实例与实例记录 ===
    _entry(
        "instance_lock_unavailable",
        "无法建立单实例锁",
        "PDF Reader 无法创建用于判断“是否已有实例在运行”的内核锁。",
        _GUIDE_LOGS,
    ),
    _entry(
        "instance_record_unwritable",
        "无法写入实例状态",
        "PDF Reader 无法在 data/runtime 下发布本次运行的实例状态。",
        "请确认程序目录可写；若问题持续，请复制诊断信息并查看日志。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "instance_record_missing",
        "无法确认已运行的实例",
        "检测到已有实例持有单实例锁，但它还没有发布可用的状态信息。",
        "请稍候重试；若持续失败，请在任务管理器中结束 PDF Reader 后重新启动。",
        ACTION_RETRY,
    ),
    _entry(
        "instance_record_invalid",
        "实例状态不可用",
        "已运行实例的状态信息无法解析或校验。",
        "请稍候重试；若持续失败，请在任务管理器中结束 PDF Reader 后重新启动。",
        ACTION_RETRY,
    ),
    _entry(
        "existing_instance_unhealthy",
        "已运行实例未就绪",
        "已有实例持有单实例锁，但健康探测没有通过。",
        "请稍候重试；程序不会终止已有实例，也不会启动第二个服务。",
        ACTION_RETRY,
    ),
    _entry(
        "existing_instance_unreachable",
        "无法联系已运行实例",
        "已有实例持有单实例锁，但启动器无法联系它的控制通道。",
        "请稍候重试；程序不会终止已有实例，也不会启动第二个服务。",
        ACTION_RETRY,
    ),
    _entry(
        "launcher_control_rejected",
        "已运行实例拒绝激活",
        "已运行的实例没有接受打开阅读器的请求。",
        "请稍候重试；若持续失败，请结束所有 PDF Reader 进程后重新启动。",
        ACTION_RETRY,
    ),
    _entry(
        "launcher_control_unreachable",
        "已运行实例控制通道不可达",
        "启动器无法连接已运行实例的本机控制通道。",
        "请稍候重试；若持续失败，请结束所有 PDF Reader 进程后重新启动。",
        ACTION_RETRY,
    ),
    _entry(
        "launcher_control_token_invalid",
        "启动器控制令牌无效",
        "启动器内部的控制令牌没有通过校验。",
        _GUIDE_LOGS,
    ),
    # === 启动器界面 ===
    _entry(
        "launcher_ui_unavailable",
        "控制窗口不可用",
        "PDF Reader 无法创建必要的控制窗口，也不会在后台静默常驻。",
        "请确认发行包中的 Tk/Tcl 运行时完整，并且当前用户有可用的图形桌面会话。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "launcher_error_window_unavailable",
        "错误窗口不可用",
        "启动器无法显示错误窗口，只能把错误写入日志。",
        _GUIDE_LOGS,
    ),
    # === 启动服务 ===
    _entry(
        "service_path_invalid",
        "服务程序路径异常",
        "服务程序的位置不在程序文件夹内。",
        "请重新解压完整发行包后启动。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "service_executable_missing",
        "缺少服务程序",
        "程序文件夹中缺少 app 内的服务程序，发行包可能不完整或被安全软件隔离。",
        "请重新解压完整发行包；如安全软件有隔离记录，请先恢复被隔离的文件。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_resource_missing",
        "发行包资源缺失",
        "发行包缺少运行所需的程序资源或私有运行时文件。",
        "请重新解压完整发行包，不要把 app 目录与顶层启动器分开移动。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "launcher_liveness_unavailable",
        "无法建立启动器存活监督",
        "PDF Reader 无法创建用于监督服务生命周期的本机对象。",
        _GUIDE_LOGS,
        ACTION_RETRY,
    ),
    _entry(
        "service_spawn_failed",
        "无法启动本地服务",
        "启动器无法创建服务进程。",
        "请确认安全软件没有阻止程序运行；若问题持续，请复制诊断信息并查看日志。",
        ACTION_RETRY,
    ),
    _entry(
        "service_start_timeout",
        "本地服务启动超时",
        "在超时时间内没有等到本地服务通过健康检查。",
        "请重试；若持续超时，请复制诊断信息并查看 data/logs 中的日志。",
        ACTION_RETRY,
    ),
    _entry(
        "service_exited_before_ready",
        "服务在就绪前退出",
        "本地服务在完成启动前就结束了，通常意味着配置、资源或私有运行时有问题。",
        "请重试；若持续失败，请复制诊断信息并查看 data/logs 中的日志。",
        ACTION_RETRY,
    ),
    _entry(
        "service_exited_while_running",
        "服务在运行中异常退出",
        "本地服务在用户退出前意外结束，正在进行的翻译不会继续。",
        "请重试；若反复发生，请复制诊断信息并查看 data/logs 中的日志。",
        ACTION_RETRY,
    ),
    _entry(
        "service_port_in_use",
        "本地端口已被占用",
        "默认端口已被其他程序占用，PDF Reader 无法启动本地服务。",
        "请关闭占用该端口的程序后重试；PDF Reader 不会终止占用端口的程序。",
        ACTION_RETRY,
    ),
    _entry(
        "service_url_invalid",
        "服务地址无效",
        "本地服务返回的地址不是合法的 loopback 地址。",
        _GUIDE_LOGS,
    ),
    _entry(
        "launcher_interrupted",
        "启动被中断",
        "启动过程被用户中断（例如 Ctrl+C），便携服务已协作关闭。",
        "可以直接重新双击启动。",
    ),
    # === 配置与运行期用户可见错误 ===
    _entry(
        "config_invalid",
        "配置需要修复",
        "配置文件存在语法或字段错误，需要先修正配置才能开始翻译。",
        "请打开配置目录，修正 data/config/config.toml 后重新启动；也可以在首次配置页面中保存。",
        ACTION_OPEN_CONFIG_DIR,
    ),
    _entry(
        "model_download_failed",
        "模型或字体下载失败",
        "首次使用需要的模型或字体没有下载成功，翻译无法开始。",
        "请检查网络或代理设置后重试；下载文件保存在便携目录内，重试不会丢失已完成的部分。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    # === 便携数据版本、迁移与清理 ===
    _entry(
        "portable_data_schema_newer",
        "数据格式版本过新",
        "已有便携数据的格式版本高于当前程序支持的版本。",
        "请使用较新的 PDF Reader 版本启动；不要用旧版本覆盖 data 目录。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_manifest_invalid",
        "便携数据清单损坏",
        "data/portable-data.json 缺失字段、类型错误或不是合法 JSON，程序拒绝继续。",
        "可从 data/backups 恢复备份，或保留原 data 后重新解压完整程序。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_backup_missing",
        "迁移备份缺失",
        "找不到要回滚的迁移备份。",
        "请确认 data/backups 目录完整，或直接复制诊断信息提供给维护者。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_backup_incomplete",
        "迁移备份不完整",
        "迁移备份账本或文件不完整，无法安全回滚。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_write_failed",
        "便携数据写入失败",
        "写入便携数据文件失败，原有字节已保留。",
        "请确认程序目录可写、磁盘空间充足后重试。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_recovery_failed",
        "数据迁移恢复失败",
        "未提交的数据迁移没有完全恢复，程序保留了备份供人工处理。",
        "请打开程序目录，按备份目录中的说明恢复数据，或把诊断信息提供给维护者。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_target_is_link",
        "拒绝通过链接写入数据",
        "便携数据目标是符号链接或 junction，程序拒绝写入或删除。",
        "请移除该链接后重试，避免数据被写到便携目录之外。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_instance_running",
        "已有实例正在运行",
        "检测到 PDF Reader 仍在运行，因此拒绝了会影响数据目录的操作。",
        "请先退出所有 PDF Reader 实例，再重新执行该操作。",
    ),
    _entry(
        "portable_data_cleanup_category_required",
        "缺少清理分类",
        "清理命令没有指定要清理的分类。",
        "请在命令中显式给出分类（documents/models/fonts/logs/temp）。",
    ),
    _entry(
        "portable_data_cleanup_category_unknown",
        "未知清理分类",
        "清理命令给出的分类不在受支持列表中。",
        "请使用 documents/models/fonts/logs/temp 中的一个或多个分类。",
    ),
    _entry(
        "portable_data_cleanup_root_is_link",
        "清理目标目录是链接",
        "待清理的分类根是符号链接或 junction，程序整体拒绝清理。",
        "请先移除该链接，避免递归删除便携目录之外的文件。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_data_import_source_missing",
        "导入源不存在",
        "受控导入给出的旧 data 目录不存在。",
        "请确认旧 data 目录路径正确后重试。",
    ),
    _entry(
        "portable_data_import_source_unsafe",
        "导入源不安全",
        "受控导入的源目录是链接，或与目标数据根互相包含。",
        "请给出独立的真实旧 data 目录，不要使用链接或目标自身的子目录。",
    ),
    _entry(
        "portable_data_import_target_unsafe",
        "导入目标不安全",
        "受控导入的目标不是安全的便携数据目录。",
        _GUIDE_LOGS,
    ),
    _entry(
        "portable_data_import_source_unreadable",
        "导入源不可读",
        "读取旧 data 目录时失败。",
        "请确认旧 data 目录可读、磁盘连接正常后重试。",
    ),
    _entry(
        "portable_data_command_invalid",
        "数据命令无效",
        "启动器收到无法识别的数据命令。",
        "请只使用 --data-report、--clean 或 --import-data 中的一种。",
    ),
    _entry(
        "portable_data_command_conflict",
        "数据命令冲突",
        "一次只能执行一个数据命令。",
        "请只使用 --data-report、--clean 或 --import-data 中的一种。",
    ),
    _entry(
        "portable_data_command_failed",
        "数据命令失败",
        "便携数据命令执行失败。",
        _GUIDE_LOGS,
    ),
    # === 服务引导发布的就绪失败码 ===
    _entry(
        "portable_service_bootstrap_failed",
        "服务引导失败",
        "服务在建立便携运行环境时失败。",
        "请重新解压完整发行包；若问题持续，请复制诊断信息并查看日志。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "portable_service_environment_missing",
        "服务缺少受控环境",
        "服务没有从启动器收到完整的受控子进程环境。",
        "请通过顶层 PDF Reader.exe 启动，不要直接运行 app 内的服务程序。",
    ),
    _entry(
        "portable_service_layout_required",
        "服务缺少便携布局",
        "服务没有收到便携运行布局。",
        "请通过顶层 PDF Reader.exe 启动，不要直接运行 app 内的服务程序。",
    ),
    _entry(
        "portable_service_control_token_invalid",
        "服务控制令牌无效",
        "服务的控制令牌没有通过校验。",
        _GUIDE_LOGS,
    ),
    _entry(
        "portable_service_launcher_liveness_invalid",
        "服务存活监督描述符无效",
        "服务的启动器存活监督描述符不合法。",
        _GUIDE_LOGS,
    ),
    _entry(
        "portable_service_health_token_invalid",
        "服务健康令牌无效",
        "服务的健康检查令牌没有通过校验。",
        _GUIDE_LOGS,
    ),
    _entry(
        "portable_service_ready_file_missing",
        "服务缺少就绪文件路径",
        "服务没有收到就绪状态文件的位置。",
        "请通过顶层 PDF Reader.exe 启动，不要直接运行 app 内的服务程序。",
    ),
    _entry(
        "portable_service_temp_invalid",
        "服务临时目录无效",
        "服务专用临时目录不合法或不在便携数据根内。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "private_runtime_layout_required",
        "缺少私有运行时布局",
        "发行服务没有收到私有 Python 运行时布局。",
        "请通过顶层 PDF Reader.exe 启动，并使用完整发行包。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "private_runtime_executable_invalid",
        "私有运行时解释器无效",
        "发行服务使用的不是 app 内的私有解释器。",
        "请重新解压完整发行包，不要用系统 Python 直接运行服务。",
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "private_runtime_user_site_enabled",
        "私有运行时隔离不完整",
        "发行服务检测到用户 site-packages 仍然生效。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "private_runtime_safe_path_disabled",
        "私有运行时安全路径未启用",
        "发行服务的 Python 安全路径没有生效。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    _entry(
        "private_runtime_search_path_invalid",
        "私有运行时搜索路径异常",
        "发行服务的模块搜索路径包含 app 之外的目录。",
        _GUIDE_LOGS,
        ACTION_OPEN_PROGRAM_DIR,
    ),
    # === 关闭通道（内部稳定码，仍然给用户可读兜底） ===
    _entry(
        "service_shutdown_rejected",
        "服务拒绝协作退出",
        "协作退出请求没有被本地服务接受。",
        _GUIDE_LOGS,
    ),
    _entry(
        "service_shutdown_unreachable",
        "无法联系服务退出通道",
        "无法连接到本地服务的协作退出通道。",
        _GUIDE_LOGS,
    ),
)

ERROR_CATALOG: dict[str, ErrorPresentation] = {entry.code: entry for entry in _CATALOG_ENTRIES}


# 需求 2 固定的六类失败：每一类都必须至少有一个带安全文案（且可恢复时带入口）的代表码。
REQUIRED_ERROR_CLASSES: dict[str, tuple[str, ...]] = {
    "unwritable_directory": (
        "portable_data_not_writable",
        "portable_data_directory_unavailable",
        "portable_layout_unavailable",
    ),
    "config_error": ("config_invalid",),
    "port_conflict": ("service_port_in_use",),
    "missing_resource": ("portable_resource_missing", "service_executable_missing"),
    "model_download_failure": ("model_download_failed",),
    "service_abnormal_exit": ("service_exited_while_running", "service_exited_before_ready"),
}

_GENERIC_PRESENTATION = ErrorPresentation(
    code="unknown",
    title="启动失败",
    summary="PDF Reader 启动过程中遇到未预期的错误。",
    guidance="请重试；若持续失败，请复制诊断信息并把 data/logs 中的日志提供给维护者。",
    recovery=ACTION_OPEN_PROGRAM_DIR,
)


def describe_error(code: str) -> ErrorPresentation:
    """返回稳定错误码的用户可读文案；未知码落到安全兜底并保留真实码。"""

    key = code if isinstance(code, str) and code else "unknown"
    known = ERROR_CATALOG.get(key)
    if known is not None:
        return known
    return ErrorPresentation(
        code=key,
        title=_GENERIC_PRESENTATION.title,
        summary=_GENERIC_PRESENTATION.summary,
        guidance=_GENERIC_PRESENTATION.guidance,
        recovery=_GENERIC_PRESENTATION.recovery,
    )


def format_failure_message(code: str, detail: str) -> str:
    """启动器与错误窗口共用的稳定行格式，保证 CLI/发行语义不漂移。"""

    return f"ERROR [{code}]: {detail}"


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RUN = re.compile(r"[ \t]{2,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_HEADER_TOKEN = re.compile(
    r"(?i)\b(x-pdf-reader-(?:health|control|service)-token)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|apikey|authorization|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"health[_-]?token|control[_-]?token|service[_-]?token|token|password|passwd|secret)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PROMPT_LINE = re.compile(
    r"(?im)^(?P<prefix>.*?)(?P<key>prompt|system_prompt|user_prompt|default_system_prompt|content|"
    r"pdf_text|document_text)\s*[:=].*$"
)
_PROMPT_QUOTED = re.compile(
    r"(?i)\b(prompt|system_prompt|user_prompt|default_system_prompt|content|pdf_text|document_text)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*')"
)
_TOKEN_PREFIX = re.compile(r"(?i)\b(?:launcher|health|service)-token-[A-Za-z0-9_-]+")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{8,}")
_WINDOWS_USER_DIR = re.compile(r"(?i)([A-Za-z]:\\+Users\\+)[^\\/\s]+")
_POSIX_USER_DIR = re.compile(r"(?<![\w.])(/(?:home|Users)/)[^/\s]+")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_LONG_OPAQUE = re.compile(r"\b[A-Za-z0-9_-]{43,}\b")


def _path_replacements(portable_root: Path | None, home: Path | None) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    if portable_root is not None:
        values.append((str(portable_root), "<portable-root>"))
    resolved_home = home
    if resolved_home is None:
        try:
            resolved_home = Path(os.path.expanduser("~"))
        except (RuntimeError, OSError):
            resolved_home = None
    if resolved_home is not None:
        values.append((str(resolved_home), "<home>"))
    try:
        values.append((tempfile.gettempdir(), "<temp>"))
    except (RuntimeError, OSError):
        pass
    return tuple(value for value in values if value[0])


def sanitize_diagnostic_text(
    text: Any,
    *,
    replacements: tuple[tuple[str, str], ...] = (),
    home: Path | None = None,
    portable_root: Path | None = None,
    limit: int = MAX_DIAGNOSTIC_DETAIL_CHARS,
) -> str:
    """把任意文本收敛为可安全分享的诊断片段：脱敏、去控制字符并限长。"""

    if not isinstance(text, str):
        text = str(text)
    safe = _CONTROL_CHARS.sub(" ", text)
    effective = replacements + (() if replacements else _path_replacements(portable_root, home))
    for value, placeholder in sorted(effective, key=lambda item: len(item[0]), reverse=True):
        if value:
            safe = safe.replace(value, placeholder)
    safe = _BEARER.sub("Bearer <redacted>", safe)
    safe = _HEADER_TOKEN.sub(lambda match: f"{match.group(1)}=<redacted>", safe)
    safe = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}=<redacted>", safe)
    safe = _PROMPT_LINE.sub(lambda match: f"{match.group('prefix')}{match.group('key')}=<redacted>", safe)
    safe = _PROMPT_QUOTED.sub(lambda match: f"{match.group(1)}=<redacted>", safe)
    safe = _TOKEN_PREFIX.sub("<redacted>", safe)
    safe = _OPENAI_KEY.sub("<redacted>", safe)
    safe = _GOOGLE_KEY.sub("<redacted>", safe)
    safe = _WINDOWS_USER_DIR.sub(r"\1<user>", safe)
    safe = _POSIX_USER_DIR.sub(r"\1<user>", safe)
    safe = _LONG_HEX.sub("<redacted>", safe)
    safe = _LONG_OPAQUE.sub("<redacted>", safe)
    safe = _WHITESPACE_RUN.sub(" ", safe).strip()
    if len(safe) > limit:
        safe = safe[:limit] + "…"
    return safe


def _platform_label() -> str:
    try:
        return f"{platform.platform()} ({platform.machine()})"
    except Exception:  # noqa: BLE001 - 诊断信息不允许因平台探测失败而中断
        return "unknown"


def build_diagnostics(
    *,
    presentation: ErrorPresentation,
    detail: str,
    app_version: str = "",
    exit_code: int | None = None,
    portable_root: Path | None = None,
    home: Path | None = None,
    platform_label: str | None = None,
    clock: Callable[[], datetime] | None = None,
    log_relative: str = DEFAULT_LOG_RELATIVE,
) -> str:
    """生成可复制的安全诊断文本：只包含版本、错误码、文案与脱敏后的细节。"""

    now = (clock or (lambda: datetime.now(UTC)))()
    safe_detail = sanitize_diagnostic_text(
        detail,
        home=home,
        portable_root=portable_root,
        limit=MAX_DIAGNOSTIC_DETAIL_CHARS,
    )
    lines = (
        DIAGNOSTICS_HEADER,
        f"应用版本：{app_version or '未知'}",
        f"生成时间：{now.astimezone(UTC).isoformat()}",
        f"运行系统：{platform_label if platform_label is not None else _platform_label()}",
        f"错误码：{presentation.code}",
        f"问题：{presentation.title}",
        f"说明：{presentation.summary}",
        f"建议：{presentation.guidance}",
        f"进程退出码：{exit_code if exit_code is not None else '未知'}",
        f"日志位置：{log_relative}",
        "详细信息：",
        safe_detail or "（无）",
    )
    return "\n".join(lines)[:MAX_DIAGNOSTIC_TEXT_CHARS]


def open_directory(path: Path) -> bool:
    """用系统文件管理器打开目录；不可用时退化到默认浏览器的 file:// 视图。"""

    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        try:
            startfile(str(path))
            return True
        except OSError as exc:
            logger.warning("无法用文件管理器打开目录：%s", exc)
    try:
        return bool(webbrowser.open(path.as_uri()))
    except Exception:  # noqa: BLE001 - 打开目录失败不影响服务本身
        logger.exception("打开目录失败")
        return False


class ErrorWindow(Protocol):
    """错误窗口最小契约：run 阻塞到用户选择退出或重试为止。"""

    def run(self) -> str: ...

    def close(self) -> None: ...


ErrorWindowFactory = Callable[..., "ErrorWindow | None"]


class _TkinterErrorWindow:
    """固定错误窗口：复制安全诊断 / 打开日志目录 /（可恢复入口）/ 退出。"""

    def __init__(
        self,
        *,
        root: Any,
        ttk_module: Any,
        presentation: ErrorPresentation,
        diagnostics: str,
        clipboard_writer: Callable[[str], Any] | None = None,
        open_logs: Callable[[], Any] | None = None,
        recovery_dispatch: Callable[[str], Any] | None = None,
    ) -> None:
        self._root = root
        self._presentation = presentation
        self._diagnostics = diagnostics
        self._clipboard_writer = clipboard_writer if clipboard_writer is not None else _tk_clipboard_writer(root)
        self._open_logs = open_logs
        self._recovery_dispatch = recovery_dispatch
        self._closed = False
        self.selected_action = ACTION_QUIT
        root.title(ERROR_WINDOW_TITLE)
        root.resizable(False, False)
        frame = ttk_module.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        heading = f"{presentation.title}（错误码：{presentation.code}）"
        ttk_module.Label(frame, text=heading, wraplength=460, justify="left").grid(row=0, column=0, sticky="w")
        ttk_module.Label(frame, text=presentation.summary, wraplength=460, justify="left").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk_module.Label(frame, text=presentation.guidance, wraplength=460, justify="left").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        row = 3
        self._add_button(ttk_module, frame, row=row, text=COPY_DIAGNOSTICS_LABEL, command=self._copy_diagnostics)
        row += 1
        self._add_button(ttk_module, frame, row=row, text=OPEN_LOGS_LABEL, command=self._open_logs_action)
        row += 1
        recovery_label = RECOVERY_LABELS.get(presentation.recovery or "")
        if recovery_label is not None:
            self._add_button(ttk_module, frame, row=row, text=recovery_label, command=self._recover)
            row += 1
        self._add_button(ttk_module, frame, row=row, text=QUIT_LABEL, command=self.close)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _add_button(self, ttk_module: Any, frame: Any, *, row: int, text: str, command: Callable[[], Any]) -> None:
        ttk_module.Button(frame, text=text, width=20, command=command).grid(row=row, column=0, sticky="ew", pady=2)

    def _copy_diagnostics(self) -> None:
        try:
            self._clipboard_writer(self._diagnostics)
        except Exception:  # noqa: BLE001 - 复制失败不能终止错误窗口
            logger.exception("复制诊断信息失败")

    def _open_logs_action(self) -> None:
        if self._open_logs is None:
            return
        try:
            self._open_logs()
        except Exception:  # noqa: BLE001 - 打开日志失败不能终止错误窗口
            logger.warning("打开日志目录失败", exc_info=True)

    def _recover(self) -> None:
        action = self._presentation.recovery
        if action == ACTION_RETRY:
            self.selected_action = ACTION_RETRY
            self.close()
            return
        if action is not None and self._recovery_dispatch is not None:
            try:
                self._recovery_dispatch(action)
            except Exception:  # noqa: BLE001 - 恢复入口失败不能终止错误窗口
                logger.warning("执行恢复入口失败 action=%s", action, exc_info=True)

    def run(self) -> str:
        self._root.mainloop()
        return self.selected_action

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._root.destroy()
        except Exception:  # noqa: BLE001 - 关闭窗口失败不能影响启动器收尾
            logger.warning("错误窗口关闭失败", exc_info=True)


def _tk_clipboard_writer(root: Any) -> Callable[[str], Any]:
    def write(text: str) -> None:
        root.clipboard_clear()
        root.clipboard_append(text)
        # Windows 上 Tk 只有在事件循环真正处理过剪贴板请求后才会接管剪贴板所有权；
        # 直接关闭窗口会让内容丢失。优先调用 update()，没有它时退化为 update_idletasks()。
        updater = getattr(root, "update", None)
        if callable(updater):
            updater()
            return
        idle = getattr(root, "update_idletasks", None)
        if callable(idle):
            idle()

    return write


def _import_tkinter() -> tuple[Any, Any] | None:
    """按需导入 tkinter/ttk；缺少 Tcl/Tk 或 GUI 依赖时返回 None。"""

    try:
        import tkinter
        from tkinter import ttk
    except Exception:  # noqa: BLE001 - 缺少 GUI 依赖不是启动失败
        logger.error("当前环境没有可用的 tkinter，无法显示错误窗口")
        return None
    return tkinter, ttk


def create_error_window(
    *,
    presentation: ErrorPresentation,
    diagnostics: str,
    clipboard_writer: Callable[[str], Any] | None = None,
    open_logs: Callable[[], Any] | None = None,
    recovery_dispatch: Callable[[str], Any] | None = None,
) -> ErrorWindow | None:
    """创建错误窗口；没有图形会话或控件失败时返回 None，由调用方退化到日志。"""

    modules = _import_tkinter()
    if modules is None:
        return None
    tkinter_module, ttk_module = modules
    try:
        root = tkinter_module.Tk()
    except Exception:  # noqa: BLE001 - 没有图形会话时退化到日志
        logger.error("无法创建错误窗口（没有图形会话）", exc_info=True)
        return None
    try:
        return _TkinterErrorWindow(
            root=root,
            ttk_module=ttk_module,
            presentation=presentation,
            diagnostics=diagnostics,
            clipboard_writer=clipboard_writer,
            open_logs=open_logs,
            recovery_dispatch=recovery_dispatch,
        )
    except Exception:  # noqa: BLE001 - 初始化失败时退化到日志
        logger.error("错误窗口初始化失败", exc_info=True)
        try:
            root.destroy()
        except Exception:  # noqa: BLE001 - 清理失败无需上报
            pass
        return None


@dataclass(frozen=True, slots=True)
class RecordedFailure:
    """一次启动失败：稳定错误码、原始细节与约定的启动器退出码。"""

    code: str
    detail: str
    exit_code: int | None = None


class FailureReporter:
    """收集启动失败并把用户可读展示与安全诊断交给错误窗口。

    记录始终复用调用方注入的 report（启动器里就是 `_report_error`），因此 stderr
    与 data/logs 中的稳定行格式与 CLI/开发模式完全一致。present() 只在显式启用 UI
    且确实发生过失败时创建窗口；窗口不可用时只写日志，不改变退出码。
    """

    def __init__(
        self,
        *,
        show_ui: bool,
        report: Callable[[str], None],
        app_version: str = "",
        launcher_executable: str | Path | None = None,
        home: Path | None = None,
    ) -> None:
        self._show_ui = bool(show_ui)
        self._report = report
        self._app_version = app_version
        self._launcher_executable = launcher_executable
        self._home = home
        self._failure: RecordedFailure | None = None

    @property
    def failure(self) -> RecordedFailure | None:
        return self._failure

    @property
    def shows_ui(self) -> bool:
        return self._show_ui

    def record(self, code: str, detail: str, *, exit_code: int | None = None) -> None:
        """记录失败并以与 CLI 完全相同的稳定行格式写入 stderr 与日志。"""

        self._failure = RecordedFailure(code=code, detail=detail, exit_code=exit_code)
        self._report(format_failure_message(code, detail))

    def clear(self) -> None:
        self._failure = None

    def present(
        self,
        *,
        window_factory: ErrorWindowFactory | None = None,
        clipboard_writer: Callable[[str], Any] | None = None,
        open_logs: Callable[[], Any] | None = None,
        recovery_dispatch: Callable[[str], Any] | None = None,
        platform_label: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> str | None:
        """显示错误窗口并返回用户选择；没有失败、未启用 UI 或窗口不可用时返回 None。"""

        failure = self._failure
        if not self._show_ui or failure is None:
            return None
        presentation = describe_error(failure.code)
        diagnostics = build_diagnostics(
            presentation=presentation,
            detail=failure.detail,
            app_version=self._app_version,
            exit_code=failure.exit_code,
            portable_root=self.portable_root(),
            home=self._home,
            platform_label=platform_label,
            clock=clock,
        )
        factory = create_error_window if window_factory is None else window_factory
        selected_open_logs = self.default_open_logs() if open_logs is None else open_logs
        selected_recovery = self.default_recovery_dispatch() if recovery_dispatch is None else recovery_dispatch
        try:
            window = factory(
                presentation=presentation,
                diagnostics=diagnostics,
                clipboard_writer=clipboard_writer,
                open_logs=selected_open_logs,
                recovery_dispatch=selected_recovery,
            )
        except Exception:  # noqa: BLE001 - 窗口构造失败只能退化到日志
            logger.error("无法显示错误窗口", exc_info=True)
            window = None
        if window is None:
            self._report(
                format_failure_message(
                    "launcher_error_window_unavailable",
                    f"{presentation.title}（错误码 {failure.code}）；请把 data/logs 提供给维护者",
                )
            )
            return None
        try:
            return window.run()
        except Exception:  # noqa: BLE001 - 窗口运行失败不能改变启动器退出码
            logger.error("错误窗口运行失败", exc_info=True)
            return None
        finally:
            try:
                window.close()
            except Exception:  # noqa: BLE001 - 关闭失败无需上报
                pass

    def portable_root(self) -> Path | None:
        """从入口 EXE 位置尽力推导便携根；只用于打开目录与路径脱敏。"""

        if self._launcher_executable is None:
            return None
        try:
            return Path(self._launcher_executable).expanduser().resolve(strict=False).parent
        except (OSError, ValueError, RuntimeError):
            return None

    def default_open_logs(self) -> Callable[[], bool]:
        root = self.portable_root()

        def opener() -> bool:
            if root is None:
                return False
            path = root / "data" / "logs"
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False
            return open_directory(path)

        return opener

    def default_recovery_dispatch(self) -> Callable[[str], bool]:
        root = self.portable_root()

        def dispatch(action: str) -> bool:
            if root is None:
                return False
            if action == ACTION_OPEN_CONFIG_DIR:
                return open_directory(root / "data" / "config")
            if action == ACTION_OPEN_PROGRAM_DIR:
                return open_directory(root)
            if action == ACTION_OPEN_LOGS:
                return open_directory(root / "data" / "logs")
            return False

        return dispatch
