"""隔離された作業コピーと差分生成。

方針:
- 元の作業ツリーには一切書き込まない。git worktree も使わない
  （worktree は元リポジトリの .git 配下にメタデータを書くため）。
- 代わりに 2 つのディレクトリを作る:
    baseline/  取り込んだ時点の原本スナップショット（読み取り専用の基準）
    work/      Qwen が編集する作業コピー
  差分は git diff --no-index baseline work で取る。新規ファイルも差分に含まれる。
- 未コミット変更は破棄しない。コピー元は「いま実際にディスクにある内容」なので、
  未コミットの変更もそのまま作業コピーへ反映される。
- 取り込んだ各ファイルの sha256 を記録し、後で適用するときの競合検出に使う。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import Sandbox

MAX_COPY_FILES = 2000
MAX_COPY_BYTES = 64 * 1024 * 1024
_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "dist", "build"}


class WorkingCopyError(RuntimeError):
    """作業コピーを準備できなかった。"""


@dataclass
class WorkingCopy:
    task_dir: Path
    baseline_dir: Path
    work_dir: Path
    project_root: Path
    base_hashes: dict[str, str] = field(default_factory=dict)
    git_head: str | None = None
    git_dirty_files: list[str] = field(default_factory=list)
    copied_file_count: int = 0
    copied_bytes: int = 0

    def provenance(self) -> dict:
        """何を基準にした作業コピーかの記録。適用時の競合検出に使う。"""
        return {
            "project_root": str(self.project_root),
            "git_head": self.git_head,
            "git_dirty_files_at_copy_time": self.git_dirty_files,
            "copied_file_count": self.copied_file_count,
            "copied_bytes": self.copied_bytes,
            "base_sha256": self.base_hashes,
        }


def _git(project_root: Path, *args: str, strip: bool = True) -> str | None:
    """git を 1 回実行して標準出力を返す。失敗したら None。

    strip=False は --porcelain のように行頭の空白に意味がある出力用。
    ステータス欄は " M path" のように先頭が空白になりうるので、
    ここで strip すると 1 文字ずれる。
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() if strip else completed.stdout


def prepare_working_copy(
    task_dir: Path, project_root: Path, sandbox: Sandbox
) -> WorkingCopy:
    """許可範囲のファイルを baseline/ と work/ に取り込む。"""
    baseline_dir = task_dir / "baseline"
    work_dir = task_dir / "work"
    for directory in (baseline_dir, work_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

    copy = WorkingCopy(
        task_dir=task_dir,
        baseline_dir=baseline_dir,
        work_dir=work_dir,
        project_root=project_root,
        git_head=_git(project_root, "rev-parse", "HEAD"),
    )
    porcelain = _git(project_root, "status", "--porcelain", strip=False)
    if porcelain:
        # 書式は "XY PATH"。X と Y はステータス 1 文字ずつで、空白もありうる。
        copy.git_dirty_files = [line[3:] for line in porcelain.splitlines() if len(line) > 3]

    for source in _files_to_copy(sandbox):
        relative = source.relative_to(project_root)
        size = source.stat().st_size
        if copy.copied_file_count >= MAX_COPY_FILES:
            raise WorkingCopyError(
                f"取り込み対象が {MAX_COPY_FILES} ファイルを超えました。"
                "allowed_read_paths / allowed_write_paths を絞ってください。"
            )
        if copy.copied_bytes + size > MAX_COPY_BYTES:
            raise WorkingCopyError(
                f"取り込み対象が {MAX_COPY_BYTES // (1024 * 1024)} MiB を超えました。"
                "allowed_read_paths / allowed_write_paths を絞ってください。"
            )
        for destination_root in (baseline_dir, work_dir):
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        copy.base_hashes[str(relative)] = _sha256(source)
        copy.copied_file_count += 1
        copy.copied_bytes += size

    if copy.copied_file_count == 0:
        raise WorkingCopyError(
            "取り込めるファイルが 1 つもありませんでした。"
            "allowed_read_paths / allowed_write_paths を確認してください。"
        )

    (task_dir / "provenance.json").write_text(
        json.dumps(copy.provenance(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return copy


def _files_to_copy(sandbox: Sandbox) -> list[Path]:
    seen: set[Path] = set()
    results: list[Path] = []
    for root in sandbox.read_roots:
        if root.is_file():
            if sandbox.is_readable(root) and root not in seen:
                seen.add(root)
                results.append(root)
            continue
        for current, dir_names, file_names in os.walk(root):
            dir_names[:] = [d for d in dir_names if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
            for file_name in sorted(file_names):
                candidate = (Path(current) / file_name).resolve(strict=False)
                if candidate in seen or not sandbox.is_readable(candidate):
                    continue
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                seen.add(candidate)
                results.append(candidate)
    return sorted(results)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_diff(copy: WorkingCopy) -> tuple[str, list[str]]:
    """baseline と work の差分（unified diff）と、変更されたファイルの一覧を返す。

    git diff --no-index は差分があると終了コード 1 を返す。これは正常。
    """
    completed = subprocess.run(
        [
            "git",
            "-c", "core.quotepath=false",
            "diff",
            "--no-index",
            "--no-color",
            "--",
            copy.baseline_dir.name,
            copy.work_dir.name,
        ],
        cwd=copy.task_dir,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise WorkingCopyError(f"git diff --no-index が失敗しました: {completed.stderr[:500]}")

    diff_text = _rewrite_diff_paths(completed.stdout, copy.baseline_dir.name, copy.work_dir.name)
    changed = sorted(_changed_paths(copy))
    return diff_text, changed


def _rewrite_diff_paths(diff_text: str, baseline_name: str, work_name: str) -> str:
    """差分ヘッダの a/baseline/... b/work/... を a/... b/... に直す。

    こうするとプロジェクトルートで git apply -p1 がそのまま通る。
    書き換えるのはパスが現れるヘッダ行だけで、本文の行には触れない。
    """
    replacements = ((f"a/{baseline_name}/", "a/"), (f"b/{work_name}/", "b/"))
    rewritten: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith(("diff --git ", "--- ", "+++ ", "rename ", "copy ")):
            for before, after in replacements:
                line = line.replace(before, after)
        rewritten.append(line)
    return "".join(rewritten)


def _changed_paths(copy: WorkingCopy) -> set[str]:
    """baseline と work を突き合わせ、内容が違う／新規のファイルを拾う。"""
    changed: set[str] = set()

    def snapshot(base: Path) -> dict[str, str]:
        table: dict[str, str] = {}
        for current, dir_names, file_names in os.walk(base):
            dir_names[:] = [d for d in dir_names if d != ".git"]
            for file_name in file_names:
                full = Path(current) / file_name
                table[str(full.relative_to(base))] = _sha256(full)
        return table

    before = snapshot(copy.baseline_dir)
    after = snapshot(copy.work_dir)
    for relative, digest in after.items():
        if before.get(relative) != digest:
            changed.add(relative)
    for relative in before:
        if relative not in after:
            changed.add(relative)
    return changed


def detect_apply_conflicts(copy: WorkingCopy) -> list[str]:
    """取り込み後に元ファイルが変わっていないかを sha256 で確かめる。"""
    conflicts: list[str] = []
    for relative, recorded in copy.base_hashes.items():
        original = copy.project_root / relative
        if not original.is_file():
            conflicts.append(f"{relative}: 取り込み後に削除された")
            continue
        if _sha256(original) != recorded:
            conflicts.append(f"{relative}: 取り込み後に変更された")
    return conflicts
