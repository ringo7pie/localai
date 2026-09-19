"""Qwen 自身が呼ぶツールの定義と実行。

いずれも Sandbox を通してからファイルに触る。
任意シェル実行は提供しない（ビルド・テストは親の権限管理下で行う方針）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sandbox import AccessDenied, Sandbox

_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "dist", "build"}
_MAX_READ_LINES = 400
_BINARY_SNIFF_BYTES = 4096


class ToolInvocationError(RuntimeError):
    """ツール名・引数が不正、または実行できなかった。"""


@dataclass
class ToolOutcome:
    text: str
    is_error: bool = False


def read_only_tool_specs() -> list[dict[str, Any]]:
    """qwen_research 用。読み取り専用。"""
    return [_LIST_FILES, _SEARCH_TEXT, _READ_FILE, _REPORT_FINDINGS]


def implement_tool_specs() -> list[dict[str, Any]]:
    """qwen_implement 用。作業コピー内での書き込みを含む。"""
    return [_LIST_FILES, _SEARCH_TEXT, _READ_FILE, _WRITE_FILE, _REPLACE_IN_FILE, _REPORT_CHANGES]


_LIST_FILES = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "許可範囲内のファイル一覧を返す。ディレクトリは再帰的にたどる。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "project_root からの相対パス。省略時はルート全体。"},
                "max_entries": {"type": "integer", "description": "返す最大件数。既定 300。"},
            },
            "required": [],
        },
    },
}

_SEARCH_TEXT = {
    "type": "function",
    "function": {
        "name": "search_text",
        "description": "許可範囲内を全文検索し、ファイルパスと行番号と該当行を返す。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索する文字列。"},
                "path": {"type": "string", "description": "検索対象の相対パス。省略時はルート全体。"},
                "is_regex": {"type": "boolean", "description": "true なら Python 正規表現として扱う。既定 false。"},
                "max_results": {"type": "integer", "description": "返す最大件数。既定 80。"},
            },
            "required": ["query"],
        },
    },
}

_READ_FILE = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": f"ファイルを行範囲指定で読む。1 回に最大 {_MAX_READ_LINES} 行。返り値には行番号が付く。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "project_root からの相対パス。"},
                "start_line": {"type": "integer", "description": "開始行。1 始まり。既定 1。"},
                "end_line": {"type": "integer", "description": "終了行。含む。省略時は start_line から最大行数ぶん。"},
            },
            "required": ["path"],
        },
    },
}

_WRITE_FILE = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "作業コピー内のファイルを新規作成、または全文を置き換える。既存ファイルの一部だけ直すときは replace_in_file を使う。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "project_root からの相対パス。"},
                "content": {"type": "string", "description": "ファイルの全文。"},
            },
            "required": ["path", "content"],
        },
    },
}

_REPLACE_IN_FILE = {
    "type": "function",
    "function": {
        "name": "replace_in_file",
        "description": "作業コピー内のファイルで、old_text をちょうど 1 箇所だけ new_text に置き換える。複数一致・不一致ならエラーを返す。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "project_root からの相対パス。"},
                "old_text": {"type": "string", "description": "置換前の文字列。ファイル内で一意になるだけの文脈を含めること。"},
                "new_text": {"type": "string", "description": "置換後の文字列。"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
}

_REPORT_FINDINGS = {
    "type": "function",
    "function": {
        "name": "report_findings",
        "description": "調査結果を確定して終了する。根拠には必ず実際に読んだファイルと行番号を入れる。",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "調査結果の要約。日本語。"},
                "evidence": {
                    "type": "array",
                    "description": "根拠。実際に read_file / search_text で確認したものだけを挙げる。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "integer"},
                            "note": {"type": "string"},
                        },
                        "required": ["path", "line", "note"],
                    },
                },
                "open_questions": {
                    "type": "array",
                    "description": "確認できなかったこと、判断が必要なこと。",
                    "items": {"type": "string"},
                },
            },
            "required": ["summary", "evidence"],
        },
    },
}

_REPORT_CHANGES = {
    "type": "function",
    "function": {
        "name": "report_changes",
        "description": "実装を確定して終了する。編集が全て終わってから呼ぶ。",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "何をどう直したかの要約。日本語。"},
                "changed_files": {
                    "type": "array",
                    "description": "作成・編集したファイルの相対パス。",
                    "items": {"type": "string"},
                },
                "tests_added": {
                    "type": "array",
                    "description": "追加したテストの相対パスと、それが何を検証するか。",
                    "items": {"type": "string"},
                },
                "unverified": {
                    "type": "array",
                    "description": "自分では実行・確認できていないこと。ビルドやテストの実行結果など。",
                    "items": {"type": "string"},
                },
            },
            "required": ["summary", "changed_files"],
        },
    },
}

TERMINAL_TOOLS = {"report_findings", "report_changes"}


class ToolRunner:
    """Qwen からのツール呼び出しを、範囲制限つきで実行する。"""

    def __init__(self, sandbox: Sandbox, max_result_chars: int, allow_write: bool) -> None:
        self.sandbox = sandbox
        self.max_result_chars = max_result_chars
        self.allow_write = allow_write
        self.files_touched: set[str] = set()
        self.denied_attempts: list[str] = []

    @property
    def available_names(self) -> set[str]:
        names = {"list_files", "search_text", "read_file", "report_findings"}
        if self.allow_write:
            names = {"list_files", "search_text", "read_file", "write_file", "replace_in_file", "report_changes"}
        return names

    def run(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name not in self.available_names:
            offered = ", ".join(sorted(self.available_names))
            return ToolOutcome(
                f"エラー: ツール {name!r} はこのタスクでは使えません。使えるのは: {offered}",
                is_error=True,
            )
        if not isinstance(arguments, dict):
            return ToolOutcome(f"エラー: {name} の引数がオブジェクトではありません", is_error=True)

        handler = {
            "list_files": self._list_files,
            "search_text": self._search_text,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "replace_in_file": self._replace_in_file,
        }[name]

        try:
            text = handler(arguments)
        except AccessDenied as exc:
            self.denied_attempts.append(f"{name}: {exc}")
            return ToolOutcome(f"アクセス拒否: {exc}", is_error=True)
        except ToolInvocationError as exc:
            return ToolOutcome(f"エラー: {exc}", is_error=True)
        except OSError as exc:
            return ToolOutcome(f"エラー: ファイル操作に失敗しました: {exc}", is_error=True)

        if len(text) > self.max_result_chars:
            text = (
                text[: self.max_result_chars]
                + f"\n…（{self.max_result_chars} 文字で打ち切り。範囲を絞って呼び直すこと）"
            )
        return ToolOutcome(text)

    # --- 個別ツール ---

    def _relative(self, target: Path) -> str:
        try:
            return str(target.relative_to(self.sandbox.project_root))
        except ValueError:
            return str(target)

    def _bases_for(self, raw_path: Any) -> tuple[list[Path], str]:
        """path 引数を探索の起点に変換する。

        未指定・"." のときは許可された read_roots 全体を起点にする。
        read_roots が project_root より狭い場合、"." は範囲外になってしまうため。
        """
        if not isinstance(raw_path, str) or self.sandbox.means_everything(raw_path):
            roots = list(self.sandbox.read_roots)
            label = "、".join(self._relative(r) or "." for r in roots)
            return roots, label
        base = self.sandbox.resolve_for_read(raw_path)
        return [base], self._relative(base)

    def _list_files(self, arguments: dict[str, Any]) -> str:
        raw_path = arguments.get("path")
        max_entries = _clamp_int(arguments.get("max_entries"), default=300, low=1, high=2000)
        bases, label = self._bases_for(raw_path)
        if len(bases) == 1 and bases[0].is_file():
            return self._relative(bases[0])

        collected: list[str] = []
        for base in bases:
            if base.is_file():
                collected.append(self._relative(base))
                continue
            for candidate in _walk_files(base, self.sandbox):
                collected.append(self._relative(candidate))
                if len(collected) >= max_entries:
                    break
            if len(collected) >= max_entries:
                break

        collected = sorted(dict.fromkeys(collected))
        if not collected:
            return f"{label} に読めるファイルはありません。"
        header = f"{label} 配下のファイル {len(collected)} 件"
        if len(collected) >= max_entries:
            header += f"（{max_entries} 件で打ち切り）"
        return header + ":\n" + "\n".join(collected)

    def _search_text(self, arguments: dict[str, Any]) -> str:
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise ToolInvocationError("query は空でない文字列にしてください")
        max_results = _clamp_int(arguments.get("max_results"), default=80, low=1, high=500)
        is_regex = bool(arguments.get("is_regex"))
        bases, label = self._bases_for(arguments.get("path"))

        try:
            pattern = re.compile(query if is_regex else re.escape(query))
        except re.error as exc:
            raise ToolInvocationError(f"正規表現が不正です: {exc}") from exc

        hits: list[str] = []
        targets: list[Path] = []
        for base in bases:
            targets.extend([base] if base.is_file() else _walk_files(base, self.sandbox))
        for file_path in targets:
            if not self.sandbox.is_readable(file_path):
                continue
            if _looks_binary(file_path):
                continue
            try:
                with file_path.open(encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if pattern.search(line):
                            hits.append(f"{self._relative(file_path)}:{line_number}: {line.rstrip()[:300]}")
                            if len(hits) >= max_results:
                                break
            except OSError:
                continue
            if len(hits) >= max_results:
                break

        if not hits:
            return f"{query!r} は {label} 配下に見つかりませんでした。"
        return f"{query!r} の一致 {len(hits)} 件:\n" + "\n".join(hits)

    def _read_file(self, arguments: dict[str, Any]) -> str:
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ToolInvocationError("path は空でない文字列にしてください")
        target = self.sandbox.resolve_for_read(raw_path)
        if not target.is_file():
            raise ToolInvocationError(f"ファイルがありません: {raw_path}")
        if _looks_binary(target):
            raise ToolInvocationError(f"バイナリファイルは読めません: {raw_path}")

        start_line = _clamp_int(arguments.get("start_line"), default=1, low=1, high=10_000_000)
        end_raw = arguments.get("end_line")
        end_line = (
            start_line + _MAX_READ_LINES - 1
            if not isinstance(end_raw, int)
            else min(int(end_raw), start_line + _MAX_READ_LINES - 1)
        )

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        self.files_touched.add(self._relative(target))
        selected = lines[start_line - 1 : end_line]
        if not selected:
            return f"{self._relative(target)} は {len(lines)} 行しかありません（{start_line} 行目は範囲外）。"
        body = "\n".join(f"{start_line + i}\t{line}" for i, line in enumerate(selected))
        tail = "" if end_line >= len(lines) else f"\n…（全 {len(lines)} 行。続きは start_line={end_line + 1} で読む）"
        return f"{self._relative(target)} {start_line}-{min(end_line, len(lines))} 行:\n{body}{tail}"

    def _write_file(self, arguments: dict[str, Any]) -> str:
        raw_path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(raw_path, str) or not raw_path:
            raise ToolInvocationError("path は空でない文字列にしてください")
        if not isinstance(content, str):
            raise ToolInvocationError("content は文字列にしてください")
        target = self.sandbox.resolve_for_write(raw_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.is_file()
        target.write_text(content, encoding="utf-8")
        self.files_touched.add(self._relative(target))
        action = "上書き" if existed else "新規作成"
        return f"{self._relative(target)} を{action}しました（{len(content.splitlines())} 行）。"

    def _replace_in_file(self, arguments: dict[str, Any]) -> str:
        raw_path = arguments.get("path")
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        if not isinstance(raw_path, str) or not raw_path:
            raise ToolInvocationError("path は空でない文字列にしてください")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ToolInvocationError("old_text と new_text は文字列にしてください")
        if not old_text:
            raise ToolInvocationError("old_text が空です")
        target = self.sandbox.resolve_for_write(raw_path)
        if not target.is_file():
            raise ToolInvocationError(f"ファイルがありません: {raw_path}")

        original = target.read_text(encoding="utf-8", errors="replace")
        occurrences = original.count(old_text)
        if occurrences == 0:
            raise ToolInvocationError(
                f"old_text が {raw_path} に見つかりません。read_file で現在の内容を確認してから呼び直すこと。"
            )
        if occurrences > 1:
            raise ToolInvocationError(
                f"old_text が {raw_path} に {occurrences} 箇所一致します。一意になるまで文脈を足すこと。"
            )
        target.write_text(original.replace(old_text, new_text, 1), encoding="utf-8")
        self.files_touched.add(self._relative(target))
        return f"{self._relative(target)} の 1 箇所を置き換えました。"


def sorted_walk(base: Path):
    import os

    for current, dir_names, file_names in os.walk(base):
        yield Path(current), dir_names, file_names


def _walk_files(base: Path, sandbox: Sandbox) -> list[Path]:
    import os

    results: list[Path] = []
    for current, dir_names, file_names in os.walk(base):
        dir_names[:] = [d for d in dir_names if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
        for file_name in sorted(file_names):
            candidate = (Path(current) / file_name).resolve(strict=False)
            if sandbox.is_readable(candidate):
                results.append(candidate)
    return results


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(low, min(high, value))
