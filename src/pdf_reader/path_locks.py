"""P0-02 按规范路径共享的进程内可重入互斥锁（RLock）。

同一文档路径可能被多个 Store 实例（或迁移流程）同时持有时，必须共享同一把
锁，避免读—改—写竞态与固定 ``.tmp`` 文件冲突。使用 RLock 允许同一线程在
已持锁路径上嵌套加锁（例如有效词表编译先取得输出路径锁，再在输入路径锁内
调用 Store.load 并计算字节摘要）。锁按解析后的规范绝对路径注册并在进程内
长期复用；不同路径得到不同锁。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_registry_lock = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def lock_for_path(path: Path) -> threading.RLock:
    """返回该规范路径对应的进程内共享锁（同一路径恒为同一锁对象）。"""
    key = os.path.normcase(str(Path(path).resolve()))
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock
