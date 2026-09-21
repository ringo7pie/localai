"""プロセスの識別と生存確認。

PID だけでは使い回しを見分けられないので、boot_id と /proc/<pid>/stat の
starttime を併せて記録する。再開時に「本当に同じプロセスがまだ生きているか」を
判定するのに使う。
"""

from __future__ import annotations

import os
import signal
import socket
from pathlib import Path


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def hostname() -> str:
    return socket.gethostname()


def start_ticks(pid: int) -> int | None:
    """/proc/<pid>/stat の 22 番目（starttime）。取れなければ None。"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm はスペースや括弧を含みうるので、最後の ')' から後ろを見る。
    tail = raw[raw.rfind(")") + 2 :]
    fields = tail.split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def identity(pid: int | None = None) -> str:
    """"<boot_id>:<pid>:<starttime>" 形式の識別子。"""
    target = os.getpid() if pid is None else pid
    return f"{boot_id()}:{target}:{start_ticks(target)}"


def alive(identity_string: str | None) -> bool:
    """identity() が返した文字列のプロセスが今も生きているか。"""
    if not identity_string:
        return False
    parts = identity_string.split(":")
    if len(parts) != 3:
        return False
    recorded_boot, raw_pid, raw_start = parts
    if recorded_boot != boot_id():
        return False  # 再起動をまたいだ PID は別物
    try:
        pid = int(raw_pid)
    except ValueError:
        return False
    current = start_ticks(pid)
    if current is None:
        return False
    return str(current) == raw_start


def terminate_tree(pid: int, grace_seconds: float = 10.0) -> str:
    """そのプロセスと、同じプロセスグループの子だけを止める。

    Ollama サービスや他タスクは巻き込まない。runner は setsid して
    独立したプロセスグループを持つので、負の PID への signal が
    そのタスクの木だけに届く。
    """
    import time

    try:
        group = os.getpgid(pid)
    except ProcessLookupError:
        return "already-gone"
    if group == os.getpgid(0):
        # 自分と同じグループなら、巻き添えを避けて個別に送る。
        targets = [pid]
        send = lambda sig: os.kill(pid, sig)  # noqa: E731
    else:
        targets = [-group]
        send = lambda sig: os.killpg(group, sig)  # noqa: E731
    del targets
    try:
        send(signal.SIGTERM)
    except ProcessLookupError:
        return "already-gone"
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "terminated"
        time.sleep(0.2)
    try:
        send(signal.SIGKILL)
    except ProcessLookupError:
        return "terminated"
    return "killed"
