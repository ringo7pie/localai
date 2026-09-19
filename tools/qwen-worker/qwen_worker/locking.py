"""プロセスをまたぐ排他制御。

Claude Code と Codex はそれぞれ別プロセスで MCP サーバーを起動する。
プロセス内 Semaphore では足りないため、ファイルロック（fcntl.flock）を使う。
これで同時推論数を合計 1 に保つ。
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path


class LockBusy(RuntimeError):
    """待機上限までにロックを取得できなかった。"""


@contextmanager
def exclusive_lock(lock_path: Path, wait_sec: float, poll_interval: float = 0.25):
    """flock による排他ロック。取得できたら保持者情報を書き込む。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + wait_sec
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    holder = _read_holder(handle)
                    raise LockBusy(
                        f"ローカル推論は同時 1 件に制限されています。"
                        f"{wait_sec:.0f} 秒待っても空きませんでした（保持者: {holder}）"
                    ) from None
                time.sleep(poll_interval)

        os.ftruncate(handle, 0)
        os.lseek(handle, 0, os.SEEK_SET)
        os.write(handle, f"pid={os.getpid()} since={time.time():.0f}".encode())
        os.fsync(handle)
        yield
    finally:
        if acquired:
            try:
                os.ftruncate(handle, 0)
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(handle)


def _read_holder(handle: int) -> str:
    try:
        os.lseek(handle, 0, os.SEEK_SET)
        return os.read(handle, 256).decode("utf-8", errors="replace").strip() or "unknown"
    except OSError:
        return "unknown"


def lock_holder(lock_path: Path) -> str | None:
    """ロックが保持されているなら保持者情報、空いていれば None。"""
    if not lock_path.exists():
        return None
    handle = os.open(lock_path, os.O_RDWR)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return _read_holder(handle)
        fcntl.flock(handle, fcntl.LOCK_UN)
        return None
    finally:
        os.close(handle)
