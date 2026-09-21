"""タスク専用の作業分離。元の作業ツリーには書かない。

方針
- 基準コミットから Git worktree を作り、そこだけで編集させる。
- 元のツリーに未コミット変更があるときは、勝手に stash / reset / clean しない。
  既定では「入力待ち」で止め、依頼側が明示したときだけ複製する。
- 差分は新規・削除・バイナリも検出できる形で取る。
- worktree は OS 隔離ではない。アクセス制限は OpenCode の permission と
  ここでの秘密ファイル検査を重ねて行う。
"""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import git_binary
from .errors import BridgeError, DirtyWorkspaceError

# 既定で読み込み・複製・差分掲載の対象外にするもの。
SECRET_GLOBS = (
    "**/.env",
    "**/.env.*",
    "**/*.env",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/id_rsa*",
    "**/id_ecdsa*",
    "**/id_ed25519*",
    "**/.ssh/**",
    "**/.aws/**",
    "**/.gnupg/**",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "**/credentials.json",
    "**/service-account*.json",
    "**/*secret*",
    "**/*.kdbx",
)

# 秘密ではないと分かっているひな形。OpenCode 側の permission でも allow にしている。
SECRET_EXCEPTIONS = (
    "**/.env.example",
    "**/.env.sample",
    "**/.env.template",
    "**/*.env.example",
)

# ビルド・テストの生成物。作業中に必ず書き換わるので、変更として数えない。
# 基準コミットに誤って入っていると「変更あり」「範囲外」に化けて合格判定を落とす（実測）。
BUILD_ARTIFACT_GLOBS = (
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyo",
    "**/.pytest_cache/**",
    "**/*.egg-info/**",
)


def is_build_artifact(relative_path: str) -> bool:
    """リポジトリ相対パスがビルド生成物か。判定の仕方は is_secret_path と同じ。"""
    text = relative_path.removeprefix("./")
    for pattern in BUILD_ARTIFACT_GLOBS:
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(text, pattern.removeprefix("**/")):
            return True
    return False


def is_secret_path(relative_path: str) -> bool:
    """リポジトリ相対パスが秘密情報の既定パターンに当たるか。

    fnmatch の ``*`` は ``/`` も越えるので、``**/`` 付きのパターンは相対パス 1 本に
    そのまま当てられる。``**/`` を外した形も試すのは、リポジトリ直下の ``.env`` の
    ように先頭にディレクトリが無い場合に当てるため。

    先頭の "./" を落とすのに lstrip は使わない。lstrip は文字集合を剥がすので
    ".env" が "env" になり、秘密判定をすり抜ける（実測で取りこぼした）。
    """
    text = relative_path.removeprefix("./")
    for pattern in SECRET_EXCEPTIONS:
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(text, pattern.removeprefix("**/")):
            return False
    for pattern in SECRET_GLOBS:
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(text, pattern.removeprefix("**/")):
            return True
    return False


@dataclass
class ChangeSet:
    diff_text: str = ""
    diff_path: str | None = None
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    binary: list[str] = field(default_factory=list)
    blocked_secret_paths: list[str] = field(default_factory=list)
    ignored_build_artifacts: list[str] = field(default_factory=list)
    tree_hash: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted or self.renamed)

    def summary_line(self) -> str:
        parts = []
        if self.added:
            parts.append(f"新規 {len(self.added)}")
        if self.modified:
            parts.append(f"変更 {len(self.modified)}")
        if self.deleted:
            parts.append(f"削除 {len(self.deleted)}")
        if self.renamed:
            parts.append(f"改名 {len(self.renamed)}")
        if self.binary:
            parts.append(f"バイナリ {len(self.binary)}")
        return "、".join(parts) if parts else "変更なし"


def _git(repo: Path, *args: str, check: bool = True, strip: bool = True) -> str:
    """git を絶対パスで実行する。strip=False は先頭の空白に意味がある出力用。"""
    completed = subprocess.run(
        [git_binary(), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        raise BridgeError(
            f"git {' '.join(args)} が失敗しました（{completed.returncode}）: "
            f"{completed.stderr.strip()[:400]}"
        )
    return completed.stdout.strip() if strip else completed.stdout


def is_git_repo(path: Path) -> bool:
    completed = subprocess.run(
        [git_binary(), "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def head_commit(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def dirty_entries(repo: Path) -> list[tuple[str, str]]:
    """(ステータス2文字, パス) の一覧。無視されたファイルは含めない。"""
    raw = _git(repo, "status", "--porcelain", strip=False)
    entries: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:  # 改名
            path = path.split(" -> ", 1)[1]
        entries.append((status, path.strip('"')))
    return entries


@dataclass
class Prepared:
    worktree: Path
    base_commit: str
    copied_dirty: list[str] = field(default_factory=list)
    skipped_secrets: list[str] = field(default_factory=list)


def prepare(
    *,
    repo: Path,
    worktree: Path,
    base_commit: str | None,
    on_dirty: str = "wait",
) -> Prepared:
    """タスク用の worktree を作る。

    on_dirty:
      "wait"               未コミット変更があれば DirtyWorkspaceError で止める（既定）
      "use_head"           未コミット変更を無視し、HEAD の内容だけで作業する
      "include_uncommitted" 未コミット変更（新規ファイル含む）を worktree へ複製する
    """
    if not is_git_repo(repo):
        raise BridgeError(
            f"{repo} は Git リポジトリではありません。"
            " この版は Git worktree で作業を分離するため、Git 管理下の場所だけを対象にします。"
        )
    # 入れ子リポジトリ対策: `git -C <repo>` は repo に .git が無ければ親方向へ
    # 最寄りの .git を探しに行く。repo が入れ子リポジトリの内側のサブディレクトリ
    # （それ自体は git 管理下だがトップレベルではない）だと、意図せず外側の
    # リポジトリ（この bridge を含む localai 本体など）を掴んで作業してしまう
    # 事故になる。実際に git が見つけたトップレベルと repo が一致するか確認する。
    actual_toplevel = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if actual_toplevel != repo.resolve():
        raise BridgeError(
            f"{repo} はリポジトリのトップレベルではありません。"
            f" git が実際に掴んだトップレベルは {actual_toplevel} です。"
            " 入れ子リポジトリでは外側のリポジトリを誤って掴む事故が起きるため、"
            " リポジトリのトップレベルのパスを指定してください。"
        )
    entries = dirty_entries(repo)
    if entries and on_dirty == "wait":
        listing = "\n".join(f"  {status} {path}" for status, path in entries[:20])
        raise DirtyWorkspaceError(
            f"{repo} に未コミットの変更が {len(entries)} 件あります。\n{listing}\n"
            "勝手に stash / reset / clean はしません。どうするか指定してください:\n"
            "  on_dirty=\"use_head\"            未コミット変更を持ち込まず HEAD で作業する\n"
            "  on_dirty=\"include_uncommitted\" 未コミット変更（新規ファイル含む）を複製して作業する"
        )

    base = base_commit or head_commit(repo)
    # 指定された基準コミットが本当に存在するか確かめる。
    _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")

    if worktree.exists():
        raise BridgeError(f"作業ツリーの置き場が既にあります: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", str(worktree), base)

    prepared = Prepared(worktree=worktree, base_commit=base)
    if entries and on_dirty == "include_uncommitted":
        for status, relative in entries:
            if status.startswith("D") or status == " D":
                target = worktree / relative
                if target.exists():
                    target.unlink()
                prepared.copied_dirty.append(relative)
                continue
            source = repo / relative
            if not source.is_file():
                continue
            if is_secret_path(relative):
                prepared.skipped_secrets.append(relative)
                continue
            target = worktree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            prepared.copied_dirty.append(relative)
    return prepared


def collect_changes(worktree: Path, base_commit: str, diff_path: Path | None = None) -> ChangeSet:
    """worktree の変更を取り出す。新規・削除・バイナリも含める。

    worktree は専用のインデックスを持つので、ここで add -A しても
    元のリポジトリのインデックスには影響しない。
    """
    changes = ChangeSet()
    _git(worktree, "add", "-A")
    changes.tree_hash = _git(worktree, "write-tree")

    name_status = _git(worktree, "diff", "--cached", "--name-status", "-M", base_commit, strip=False)
    for line in name_status.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        code = fields[0]
        path = fields[-1]
        if is_secret_path(path):
            changes.blocked_secret_paths.append(path)
            continue
        if is_build_artifact(path):
            changes.ignored_build_artifacts.append(path)
            continue
        if code.startswith("A"):
            changes.added.append(path)
        elif code.startswith("M"):
            changes.modified.append(path)
        elif code.startswith("D"):
            changes.deleted.append(path)
        elif code.startswith("R"):
            changes.renamed.append(path)

    numstat = _git(worktree, "diff", "--cached", "--numstat", "-M", base_commit, strip=False)
    for line in numstat.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0] == "-" and fields[1] == "-":
            path = fields[2]
            if is_secret_path(path) or is_build_artifact(path):
                continue
            changes.binary.append(path)

    exclusions = [
        f":(exclude){path}"
        for path in (*changes.blocked_secret_paths, *changes.ignored_build_artifacts)
    ]
    changes.diff_text = _git(
        worktree,
        "diff",
        "--cached",
        "--binary",
        "-M",
        base_commit,
        "--",
        ".",
        *exclusions,
        strip=False,
    )
    if diff_path is not None and changes.diff_text:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(changes.diff_text, encoding="utf-8")
        changes.diff_path = str(diff_path)
    return changes


def verify_applies(repo: Path, diff_path: Path) -> tuple[bool, str]:
    """差分が元のリポジトリへ当たるか確認する。当てはしない。"""
    completed = subprocess.run(
        [git_binary(), "-C", str(repo), "apply", "--check", "-p1", str(diff_path)],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0, completed.stderr.strip()[:400]


def remove(repo: Path, worktree: Path) -> None:
    """worktree を片付ける。元のリポジトリの作業内容には触れない。"""
    if not worktree.exists():
        return
    subprocess.run(
        [git_binary(), "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [git_binary(), "-C", str(repo), "worktree", "prune"], capture_output=True, text=True
    )
