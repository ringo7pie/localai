"""排他制御。

2 種類ある。混同しないこと。
1. ジョブ枠 (job slot): この作業 PC で同時に走らせるタスクの数を制限する。
   flock なので、別々に起動した CLI / MCP プロセス間でも共有される。
2. 推論の直列化: これは A30 側の Ollama が n_slots=1 で行っている。
   作業 PC のロックでは、他の PC からの推論までは制御できない。
   A30 全体の制御は Ollama の OLLAMA_NUM_PARALLEL / OLLAMA_MAX_QUEUE が担う。
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SlotBusy(RuntimeError):
    """待ち時間の上限までに枠が空かなかった。"""


@contextmanager
def job_slot(lock_dir: Path, slots: int, wait_seconds: int) -> Iterator[int]:
    """slots 個のうち 1 つを掴む。掴めるまで待ち、上限を過ぎたら SlotBusy。"""
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    for index in range(slots):
        path = lock_dir / f"job-{index}.lock"
        handles.append((index, os.open(path, os.O_CREAT | os.O_RDWR, 0o600)))
    deadline = time.time() + wait_seconds
    acquired: tuple[int, int] | None = None
    try:
        while acquired is None:
            for index, handle in handles:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    continue
                acquired = (index, handle)
                break
            if acquired is None:
                if time.time() >= deadline:
                    raise SlotBusy(
                        f"ジョブ枠 {slots} 個がすべて使用中で、{wait_seconds} 秒以内に空きませんでした。"
                    )
                time.sleep(1.0)
        os.write(acquired[1], f"{os.getpid()}\n".encode())
        yield acquired[0]
    finally:
        for _, handle in handles:
            try:
                os.close(handle)
            except OSError:
                pass


@contextmanager
def exclusive_file(path: Path, wait_seconds: float = 30.0) -> Iterator[None]:
    """1 本のファイルロック。台帳の書き換えを直列化したい所で使う。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.time() + wait_seconds
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.time() >= deadline:
                    raise SlotBusy(f"{path} のロックを {wait_seconds} 秒待っても取れませんでした。")
                time.sleep(0.1)
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)
