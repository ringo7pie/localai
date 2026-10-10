"""設定の読み込みと検証。

信頼できる値はこのファイルから来るものだけ。モデルや依頼者が渡した文字列を
そのままパスやコマンドとして使わない。submit が受け取るのは
「登録済みの workspace_id」と「登録済みの検証プロファイル名」だけで、
実パスと実行コマンドの対応付けはここで解決する。
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError, NotFoundError

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("LOCAL_AI_BRIDGE_CONFIG")
    or Path.home() / ".config" / "local-ai-bridge" / "bridge.toml"
)

# 台帳を置いてはいけないファイルシステム。共有 NAS 上の SQLite はロックが壊れる。
NETWORK_FS_TYPES = {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "afs", "ceph", "glusterfs"}


@dataclass(frozen=True)
class VerifyProfile:
    """検証プロファイル。実行コマンドは argv の配列で持つ。シェルを介さない。"""

    name: str
    command: tuple[str, ...]
    timeout_sec: int
    description: str = ""


@dataclass(frozen=True)
class Workspace:
    """登録済みの作業場所。ここに無いパスでは作業しない。"""

    workspace_id: str
    path: Path
    default_verify: str | None
    verify_profiles: dict[str, VerifyProfile]

    def profile(self, name: str | None) -> VerifyProfile | None:
        chosen = name or self.default_verify
        if chosen is None:
            return None
        if chosen not in self.verify_profiles:
            raise NotFoundError(
                f"検証プロファイル {chosen!r} は workspace {self.workspace_id!r} に登録されていない。"
                f" 登録済み: {sorted(self.verify_profiles) or '(なし)'}"
            )
        return self.verify_profiles[chosen]


@dataclass(frozen=True)
class Limits:
    """予算と上限。すべて設定可能にする。選定理由は README.ja.md に書く。"""

    max_job_seconds: int = 1800
    max_model_calls: int = 40
    max_tool_calls: int = 120
    max_output_tokens_total: int = 60000
    repair_rounds: dict[str, int] = field(
        default_factory=lambda: {"standard": 1, "deep": 2, "exhaustive": 3}
    )
    max_concurrent_jobs: int = 1
    queue_wait_seconds: int = 900
    opencode_stall_seconds: int = 600
    connect_timeout_sec: int = 15
    verify_timeout_sec: int = 600
    result_summary_max_chars: int = 600
    result_max_bytes: int = 8192
    # wait_for_task が 1 回の呼び出しでブロックしてよい秒数の上限。
    # MCP_TOOL_TIMEOUT=2,100,000ms（35 分）の内側に収める。
    wait_for_task_max_sec: int = 2000


@dataclass(frozen=True)
class Config:
    config_path: Path
    ollama_base_url: str
    model: str
    opencode_binary: Path
    opencode_profile_dir: Path
    opencode_config_source: Path
    state_root: Path
    limits: Limits
    workspaces: dict[str, Workspace]
    registration_roots: tuple[Path, ...] = ()

    # --- 派生パス -------------------------------------------------------
    @property
    def ledger_path(self) -> Path:
        return self.state_root / "ledger.db"

    @property
    def tasks_dir(self) -> Path:
        return self.state_root / "tasks"

    @property
    def worktrees_dir(self) -> Path:
        return self.state_root / "worktrees"

    @property
    def job_lock_dir(self) -> Path:
        return self.state_root / "locks"

    def workspace(self, workspace_id: str) -> Workspace:
        if workspace_id not in self.workspaces:
            raise NotFoundError(
                f"workspace_id {workspace_id!r} は登録されていない。"
                f" 登録済み: {sorted(self.workspaces) or '(なし)'}"
            )
        return self.workspaces[workspace_id]

    def ensure_dirs(self) -> None:
        for directory in (self.state_root, self.tasks_dir, self.worktrees_dir, self.job_lock_dir):
            directory.mkdir(parents=True, exist_ok=True)


def _require(table: dict, key: str, where: str):
    if key not in table:
        raise ConfigError(f"{where} に {key!r} がありません。")
    return table[key]


def _filesystem_type(path: Path) -> str | None:
    """path を含むマウントの種類。/proc/mounts から最長一致で引く。"""
    try:
        entries = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    resolved = str(path.resolve())
    best: tuple[int, str] | None = None
    for line in entries:
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point, fs_type = fields[1], fields[2]
        if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
            if best is None or len(mount_point) > best[0]:
                best = (len(mount_point), fs_type)
    return best[1] if best else None


def _parse_verify_profiles(raw: dict, workspace_id: str) -> dict[str, VerifyProfile]:
    profiles: dict[str, VerifyProfile] = {}
    for name, body in raw.items():
        where = f"[workspace.{workspace_id}.verify.{name}]"
        if not isinstance(body, dict):
            raise ConfigError(f"{where} はテーブルである必要があります。")
        command = _require(body, "command", where)
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) for part in command
        ):
            raise ConfigError(
                f"{where} の command は空でない文字列の配列にしてください。"
                " シェル文字列は受け付けません（シェルを介さず実行するため）。"
            )
        timeout_sec = int(body.get("timeout_sec", 600))
        if timeout_sec <= 0:
            raise ConfigError(f"{where} の timeout_sec は 1 以上にしてください。")
        profiles[name] = VerifyProfile(
            name=name,
            command=tuple(command),
            timeout_sec=timeout_sec,
            description=str(body.get("description", "")),
        )
    return profiles


def load(path: Path | None = None) -> Config:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(
            f"設定ファイルがありません: {config_path}\n"
            "tools/local-ai-bridge/config/bridge.toml.example を写して作ってください。"
        )
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path} を TOML として読めません: {exc}") from exc

    ollama = raw.get("ollama", {})
    base_url = str(ollama.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
    model = str(_require(ollama, "model", "[ollama]"))

    opencode = raw.get("opencode", {})
    binary = Path(str(_require(opencode, "binary", "[opencode]"))).expanduser()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ConfigError(f"[opencode] binary が実行可能ファイルではありません: {binary}")

    state = raw.get("state", {})
    state_root = Path(
        str(state.get("root", Path.home() / ".local" / "state" / "local-ai-bridge"))
    ).expanduser()

    fs_type = _filesystem_type(state_root if state_root.exists() else state_root.parent)
    if fs_type in NETWORK_FS_TYPES:
        raise ConfigError(
            f"[state] root がネットワークファイルシステム（{fs_type}）の上にあります: {state_root}\n"
            "SQLite の台帳は共有 NAS 上に置かないでください。ローカルディスクを指定してください。"
        )

    profile_dir = Path(
        str(opencode.get("profile_dir", state_root / "opencode-profile"))
    ).expanduser()
    here = Path(__file__).resolve().parent.parent
    config_source = Path(
        str(opencode.get("config_source", here / "opencode-profile" / "opencode.json"))
    ).expanduser()

    limits_raw = raw.get("limits", {})
    repair = {
        "standard": int(limits_raw.get("max_repair_rounds_standard", 1)),
        "deep": int(limits_raw.get("max_repair_rounds_deep", 2)),
        "exhaustive": int(limits_raw.get("max_repair_rounds_exhaustive", 3)),
    }
    limits = Limits(
        max_job_seconds=int(limits_raw.get("max_job_seconds", 1800)),
        max_model_calls=int(limits_raw.get("max_model_calls", 40)),
        max_tool_calls=int(limits_raw.get("max_tool_calls", 120)),
        max_output_tokens_total=int(limits_raw.get("max_output_tokens_total", 60000)),
        repair_rounds=repair,
        max_concurrent_jobs=int(limits_raw.get("max_concurrent_jobs", 1)),
        queue_wait_seconds=int(limits_raw.get("queue_wait_seconds", 900)),
        opencode_stall_seconds=int(limits_raw.get("opencode_stall_seconds", 600)),
        connect_timeout_sec=int(limits_raw.get("connect_timeout_sec", 15)),
        verify_timeout_sec=int(limits_raw.get("verify_timeout_sec", 600)),
        result_summary_max_chars=int(limits_raw.get("result_summary_max_chars", 600)),
        result_max_bytes=int(limits_raw.get("result_max_bytes", 8192)),
        wait_for_task_max_sec=int(limits_raw.get("wait_for_task_max_sec", 2000)),
    )
    for name, value in (
        ("max_job_seconds", limits.max_job_seconds),
        ("max_model_calls", limits.max_model_calls),
        ("max_tool_calls", limits.max_tool_calls),
        ("max_concurrent_jobs", limits.max_concurrent_jobs),
        # 0 以下だと wait_for_task が待たずに返るか、際限なく待つ。
        # MCP_TOOL_TIMEOUT=2,100,000ms の内側に収めるため、必ず正の上限を持たせる。
        ("wait_for_task_max_sec", limits.wait_for_task_max_sec),
    ):
        if value <= 0:
            raise ConfigError(f"[limits] {name} は 1 以上にしてください（無制限にしない）。")

    registration_raw = raw.get("registration", {})
    if not isinstance(registration_raw, dict):
        raise ConfigError("[registration] はテーブルである必要があります。")
    allowed_roots_raw = registration_raw.get("allowed_roots", [])
    if not isinstance(allowed_roots_raw, list) or not all(
        isinstance(item, str) for item in allowed_roots_raw
    ):
        raise ConfigError("[registration] の allowed_roots は文字列の配列にしてください。")
    registration_roots = tuple(
        Path(item).expanduser().resolve() for item in allowed_roots_raw
    )

    workspaces: dict[str, Workspace] = {}
    for workspace_id, body in raw.get("workspace", {}).items():
        where = f"[workspace.{workspace_id}]"
        if not isinstance(body, dict):
            raise ConfigError(f"{where} はテーブルである必要があります。")
        workspace_path = Path(str(_require(body, "path", where))).expanduser()
        try:
            workspace_path = workspace_path.resolve(strict=True)
        except OSError as exc:
            raise ConfigError(f"{where} の path が存在しません: {workspace_path} ({exc})") from exc
        if not workspace_path.is_dir():
            raise ConfigError(f"{where} の path がディレクトリではありません: {workspace_path}")
        profiles = _parse_verify_profiles(body.get("verify", {}), workspace_id)
        default_verify = body.get("default_verify")
        if default_verify is not None and default_verify not in profiles:
            raise ConfigError(
                f"{where} の default_verify {default_verify!r} が verify に定義されていません。"
            )
        workspaces[workspace_id] = Workspace(
            workspace_id=workspace_id,
            path=workspace_path,
            default_verify=default_verify,
            verify_profiles=profiles,
        )

    return Config(
        config_path=config_path,
        ollama_base_url=base_url,
        model=model,
        opencode_binary=binary,
        opencode_profile_dir=profile_dir,
        opencode_config_source=config_source,
        state_root=state_root,
        limits=limits,
        workspaces=workspaces,
        registration_roots=registration_roots,
    )


def git_binary() -> str:
    """git の絶対パス。エイリアスや PATH に頼らない。"""
    found = shutil.which("git")
    if not found:
        raise ConfigError("git が見つかりません。")
    return found
