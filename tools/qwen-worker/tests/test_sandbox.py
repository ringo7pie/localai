"""アクセス範囲の境界テスト。モックではなく実ファイルで確かめる。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qwen_worker.sandbox import AccessDenied, build_sandbox, resolve_project_root  # noqa: E402

DENIED_GLOBS = (
    "**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/.ssh/**",
    "**/credentials*", "**/secrets*",
)

failures: list[str] = []


def check(label: str, condition: bool) -> None:
    print(("PASS  " if condition else "FAIL  ") + label)
    if not condition:
        failures.append(label)


def denies(sandbox, path: str, write: bool = False) -> bool:
    try:
        sandbox.resolve_for_write(path) if write else sandbox.resolve_for_read(path)
    except AccessDenied:
        return True
    return False


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_temp:
        temp = Path(raw_temp).resolve()
        project = temp / "project"
        outside = temp / "outside"
        (project / "src").mkdir(parents=True)
        (project / "docs").mkdir()
        outside.mkdir()
        (project / "src" / "app.py").write_text("x = 1\n")
        (project / "docs" / "note.md").write_text("note\n")
        (project / ".env").write_text("TOKEN=secret\n")
        (project / "src" / "server.key").write_text("key\n")
        (outside / "loot.txt").write_text("loot\n")
        os.symlink(outside / "loot.txt", project / "src" / "link-out.txt")

        sandbox = build_sandbox(project, ["src"], ["src"], DENIED_GLOBS)

        # 通常の許可
        check("src 配下は読める", sandbox.resolve_for_read("src/app.py").is_file())
        check("src 配下は書ける", sandbox.resolve_for_write("src/new.py").name == "new.py")

        # 範囲外
        check("許可外ディレクトリの読み取りを拒否", denies(sandbox, "docs/note.md"))
        check("パストラバーサルを拒否", denies(sandbox, "../outside/loot.txt"))
        check("絶対パスでの範囲外を拒否", denies(sandbox, str(outside / "loot.txt")))
        check("シンボリックリンク経由の範囲外を拒否", denies(sandbox, "src/link-out.txt"))
        check("NUL 文字を拒否", denies(sandbox, "src/a\x00b"))

        # 秘密情報
        check(".env を拒否", denies(sandbox, "../.env"))
        secret_sandbox = build_sandbox(project, ["."], ["src"], DENIED_GLOBS)
        check("ルート許可でも .env を拒否", denies(secret_sandbox, ".env"))
        check("ルート許可でも *.key を拒否", denies(secret_sandbox, "src/server.key"))
        check("鍵ファイルへの書き込みも拒否", denies(secret_sandbox, "src/server.key", write=True))

        # 正常なパスが誤って秘密扱いされないこと（末尾 /** パターンの退行防止）
        check("src は秘密扱いされない", not denies(secret_sandbox, "src"))
        check("docs は秘密扱いされない", not denies(secret_sandbox, "docs/note.md"))
        check("app.py は秘密扱いされない", not denies(secret_sandbox, "src/app.py"))

        # 読み取り専用タスク
        read_only = build_sandbox(project, ["src"], [], DENIED_GLOBS)
        check("読み取り専用タスクでは書けない", denies(read_only, "src/app.py", write=True))

        # project_root の検証
        try:
            resolve_project_root(str(outside), (project,))
            check("許可ルート外の project_root を拒否", False)
        except AccessDenied:
            check("許可ルート外の project_root を拒否", True)
        check(
            "許可ルート配下の project_root は通る",
            resolve_project_root(str(project / "src"), (project,)) == project / "src",
        )

    print()
    if failures:
        print(f"{len(failures)} 件失敗: " + ", ".join(failures))
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
