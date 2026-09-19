"""Qwen に渡すシステムプロンプト。

親の会話全体は渡さない。担当タスクに必要な情報だけをここに組み立てる。
"""

from __future__ import annotations

from typing import Any

_COMMON_RULES = """\
あなたはローカルで動くコードワーカーです。親のエージェント（Claude Code または Codex）から
切り出された 1 つのタスクだけを担当します。親の会話全体は渡されていません。

守ること:
- 推測で答えない。必ずツールで実際のファイルを読んでから述べる。
- 学習済みの知識をこのプロジェクトの事実として語らない。
- 許可範囲外のパスにはアクセスできない。拒否されたら範囲内で進める。
- シェルは実行できない。ビルドとテストの実行は親が行う。
- 出力は日本語。
"""

_RESEARCH_RULES = """\
あなたの仕事は調査です。ファイルを書き換えることはできません。

進め方:
1. search_text と list_files で当たりを付ける。
2. read_file で該当箇所を実際に読む。
3. 十分に裏が取れたら report_findings を呼んで終える。

report_findings の evidence には、実際に read_file か search_text で確認した
ファイルと行番号だけを入れること。読んでいない行番号を書かない。
確認できなかったことは open_questions に入れる。
"""

_IMPLEMENT_RULES = """\
あなたの仕事は実装とテストコードの作成です。
編集対象は隔離された作業コピーです。元のリポジトリではありません。

進め方:
1. search_text と read_file で対象と周辺の書き方を把握する。
2. replace_in_file で局所的に直す。新規ファイルは write_file で作る。
3. 完了条件を満たしたら report_changes を呼んで終える。

守ること:
- 既存のコードの書き方（命名、コメントの量、言語）に合わせる。
- 変更は依頼された範囲にとどめる。関係のない整形をしない。
- テストは実行できない。report_changes の unverified に「テスト未実行」と書くこと。
- 編集前に必ず read_file で現在の内容を確認する。
"""


def build_system_prompt(mode: str) -> str:
    if mode == "research":
        return _COMMON_RULES + "\n" + _RESEARCH_RULES
    if mode == "implement":
        return _COMMON_RULES + "\n" + _IMPLEMENT_RULES
    raise ValueError(f"未知のモード: {mode}")


def build_user_prompt(
    *,
    task: str,
    project_root: str,
    allowed_read_paths: list[str],
    allowed_write_paths: list[str],
    constraints: list[str],
    acceptance_criteria: list[str],
    extra_materials: list[dict[str, Any]] | None = None,
) -> str:
    sections = [f"# タスク\n{task.strip()}", f"\n# プロジェクトルート\n{project_root}"]

    read_display = allowed_read_paths or ["（プロジェクトルート全体）"]
    sections.append("\n# 読める範囲\n" + "\n".join(f"- {p}" for p in read_display))
    if allowed_write_paths:
        sections.append("\n# 書ける範囲（作業コピー内）\n" + "\n".join(f"- {p}" for p in allowed_write_paths))
    else:
        sections.append("\n# 書ける範囲\nなし。読み取り専用のタスクです。")

    if constraints:
        sections.append("\n# 制約\n" + "\n".join(f"- {c}" for c in constraints))
    if acceptance_criteria:
        sections.append("\n# 完了条件\n" + "\n".join(f"- {c}" for c in acceptance_criteria))

    if extra_materials:
        lines = ["\n# 親から渡された資料"]
        for material in extra_materials:
            source = material.get("url") or material.get("path") or "（出典未記載）"
            retrieved = material.get("retrieved_at") or "（取得日未記載）"
            lines.append(f"\n## 出典: {source}（取得日: {retrieved}）\n{material.get('content', '')}")
        sections.append("\n".join(lines))

    return "\n".join(sections)
