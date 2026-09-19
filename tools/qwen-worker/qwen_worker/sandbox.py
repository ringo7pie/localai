"""アクセス範囲の制限。

方針:
- project_root は設定の allowed_roots 配下に限る。モデルの申告だけを根拠にしない。
- 実際のアクセス判定は realpath（シンボリックリンク解決後）で行う。
  これによりパストラバーサルとリンク経由の範囲外アクセスを防ぐ。
- 秘密情報らしいパターンは読み込み・複製の対象から常に外す。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


class AccessDenied(PermissionError):
    """許可範囲外、または秘密情報とみなしたパスへのアクセス。"""


@dataclass(frozen=True)
class Sandbox:
    """1 タスク分のアクセス範囲。

    read_roots / write_roots はいずれも realpath 済みの絶対パス。
    write_roots は read_roots の部分集合として扱う（書ける場所は読める）。
    """

    project_root: Path
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    denied_globs: tuple[str, ...]

    def _is_denied_by_glob(self, target: Path) -> bool:
        """秘密情報とみなすパターンに当たるか。

        判定はフルパス 1 本に対して行う。fnmatch の ``*`` は ``/`` も越えるので、
        ``**/.env`` のようなパターンはそのままフルパスに当てられる。

        以前は「パターン末尾のセグメントをファイル名に当てる」フォールバックも
        持っていたが、``**/.ssh/**`` の末尾が ``**`` になり、あらゆる名前に
        一致してしまった（実測で src/ が秘密扱いになった）。そのため廃止した。
        """
        text = str(target)
        return any(fnmatch.fnmatch(text, pattern) for pattern in self.denied_globs)

    @staticmethod
    def _within(target: Path, roots: tuple[Path, ...]) -> bool:
        for root in roots:
            if target == root or root in target.parents:
                return True
        return False

    def _resolve(self, raw_path: str) -> Path:
        if "\x00" in raw_path:
            raise AccessDenied("パスに NUL 文字が含まれています")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        # 存在しないファイル（新規作成）も扱うため strict=False。
        # 親までのシンボリックリンクはここで解決されるので、リンク経由の脱出を防げる。
        return candidate.resolve(strict=False)

    @staticmethod
    def means_everything(raw_path: str | None) -> bool:
        """「許可された範囲すべて」を指す書き方か。

        モデルは範囲を絞らず調べ始めたいとき素直に "." を渡してくる。
        read_roots が project_root より狭いとき "." は範囲外になるので、
        ここで拾って read_roots 全体として扱う。
        """
        return raw_path is None or raw_path.strip() in ("", ".", "./", "*")

    def resolve_for_read(self, raw_path: str) -> Path:
        target = self._resolve(raw_path)
        if not self._within(target, self.read_roots):
            raise AccessDenied(f"読み取り許可範囲外です: {raw_path}")
        if self._is_denied_by_glob(target):
            raise AccessDenied(f"秘密情報として除外されているパスです: {raw_path}")
        return target

    def resolve_for_write(self, raw_path: str) -> Path:
        target = self._resolve(raw_path)
        if not self.write_roots:
            raise AccessDenied("このタスクは読み取り専用です")
        if not self._within(target, self.write_roots):
            raise AccessDenied(f"書き込み許可範囲外です: {raw_path}")
        if self._is_denied_by_glob(target):
            raise AccessDenied(f"秘密情報として除外されているパスです: {raw_path}")
        return target

    def is_readable(self, target: Path) -> bool:
        """既に realpath 済みのパスが読んでよいか。ファイル列挙のふるい分け用。"""
        return self._within(target, self.read_roots) and not self._is_denied_by_glob(target)


def resolve_project_root(raw_root: str, allowed_roots: tuple[Path, ...]) -> Path:
    """project_root を検証して realpath で返す。"""
    root = Path(raw_root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise AccessDenied(f"project_root がディレクトリではありません: {raw_root}")
    for allowed in allowed_roots:
        if root == allowed or allowed in root.parents:
            return root
    permitted = ", ".join(str(p) for p in allowed_roots)
    raise AccessDenied(
        f"project_root {root} は許可ルートの外です。許可されているのは: {permitted}"
    )


def build_sandbox(
    project_root: Path,
    allowed_read_paths: list[str] | None,
    allowed_write_paths: list[str] | None,
    denied_globs: tuple[str, ...],
) -> Sandbox:
    """相対/絶対の許可パス指定を realpath 済みのルート集合に畳む。

    allowed_read_paths が空なら project_root 全体を読み取り可能にする。
    allowed_write_paths が空なら読み取り専用。
    """

    def normalize(entries: list[str]) -> tuple[Path, ...]:
        resolved: list[Path] = []
        for entry in entries:
            candidate = Path(entry)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            candidate = candidate.resolve(strict=False)
            if candidate != project_root and project_root not in candidate.parents:
                raise AccessDenied(
                    f"許可パス {entry} が project_root {project_root} の外を指しています"
                )
            resolved.append(candidate)
        return tuple(resolved)

    read_roots = normalize(allowed_read_paths or []) or (project_root,)
    write_roots = normalize(allowed_write_paths or [])
    # 書ける場所は読めるべきなので read_roots に合流させる。
    merged_read = tuple(dict.fromkeys(read_roots + write_roots))
    return Sandbox(
        project_root=project_root,
        read_roots=merged_read,
        write_roots=write_roots,
        denied_globs=denied_globs,
    )
