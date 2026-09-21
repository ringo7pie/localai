"""OpenCode へ渡す指示文の組み立て。

クラウドの会話全体は渡さない。渡すのは、目的・変更可能範囲・変更禁止事項・
合格条件・（レビュー時は）実際の差分だけ。
"""

from __future__ import annotations

from .opencode import NO_RECURSION_PREAMBLE


def _bullets(title: str, items: list[str], empty: str = "（指定なし）") -> str:
    if not items:
        return f"## {title}\n{empty}\n"
    body = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n{body}\n"


def implement(
    *,
    goal: str,
    allowed_scope: list[str],
    forbidden: list[str],
    acceptance: list[str],
    verify_command: list[str] | None,
    extra_note: str = "",
) -> str:
    verify_text = (
        f"呼び出し側が実行する検証コマンド: `{' '.join(verify_command)}`\n"
        "このコマンドはあなたではなく呼び出し側が実行する。合格する状態にしてから終えること。\n"
        if verify_command
        else "このタスクに自動検証コマンドは登録されていない。合格条件を満たす実装にすること。\n"
    )
    return f"""{NO_RECURSION_PREAMBLE}
# 実装タスク

## 目的
{goal}

{_bullets("変更してよい範囲", allowed_scope, "（作業ツリー全体。ただし下の禁止事項に従う）")}
{_bullets("変更してはいけないもの", forbidden)}
{_bullets("合格条件", acceptance)}
## 検証
{verify_text}
## 進め方
1. 関係するファイルを grep / glob で探し、必要な部分だけ read する。全体を読み込まない。
2. edit または write で変更する。
3. 最後に、変更したファイルと変更内容を日本語で 5 行以内にまとめる。
   直せなかった点・判断に迷った点があれば「未解決:」で始まる行に書く。

{extra_note}"""


def review(
    *,
    goal: str,
    acceptance: list[str],
    diff_text: str,
    verify_summary: str,
    focus: str,
) -> str:
    return f"""{NO_RECURSION_PREAMBLE}
# レビュー（読み取り専用）

別のセッションが下の変更を行った。あなたはレビュー担当で、**ファイルを編集してはいけない**。
read / grep / glob で周辺コードを確認してよい。

## もとの目的
{goal}

{_bullets("合格条件", acceptance)}
## 検証の実行結果
{verify_summary}

## 観点
{focus}

## 変更差分
```diff
{diff_text}
```

## 出力
次の形式で、日本語で答える。推測と事実を分ける。
- 判定: OK / 要修正
- 問題点: 箇条書き。ファイル名と行がわかるなら添える。無ければ「なし」
- 境界条件で危ないケース: 箇条書き。無ければ「なし」
- 修正案: 要修正のときだけ、何をどう直すかを簡潔に
"""


def repair(*, goal: str, acceptance: list[str], findings: str, verify_summary: str) -> str:
    return f"""{NO_RECURSION_PREAMBLE}
# 修正タスク

先ほどの変更に対して、下の指摘と検証結果が出ている。指摘された点だけを直すこと。
目的の範囲を超える書き換えやリファクタリングはしない。

## もとの目的
{goal}

{_bullets("合格条件", acceptance)}
## 検証の実行結果
{verify_summary}

## 指摘
{findings}

## 出力
修正後、変更したファイルと直した内容を日本語で 5 行以内にまとめる。
直せなかった指摘があれば「未解決:」で始まる行に残す。
"""


def plan_options(*, goal: str, allowed_scope: list[str], acceptance: list[str]) -> str:
    return f"""{NO_RECURSION_PREAMBLE}
# 方針の比較（読み取り専用）

**ファイルを編集してはいけない。** 調査して方針を 2 つまで挙げ、比較するだけ。

## 目的
{goal}

{_bullets("変更してよい範囲", allowed_scope, "（作業ツリー全体）")}
{_bullets("合格条件", acceptance)}
## 出力
日本語で次の形式。
- 方針A: 概要 / 変更するファイル / 利点 / 欠点・危険
- 方針B: 概要 / 変更するファイル / 利点 / 欠点・危険（1 つしか無ければ「なし」）
- 推奨: A か B か、その理由を 2 行以内で
"""


def counterexample_review(*, goal: str, acceptance: list[str], diff_text: str) -> str:
    return f"""{NO_RECURSION_PREAMBLE}
# 反例さがし（読み取り専用）

**ファイルを編集してはいけない。** 下の変更が壊れる具体的な入力・状態を探す。
「たぶん大丈夫」は書かない。再現手順が言えるものだけを挙げる。

## もとの目的
{goal}

{_bullets("合格条件", acceptance)}
## 変更差分
```diff
{diff_text}
```

## 出力
- 反例: 入力・状態 → 期待される結果 → 実際に起きること。最大 5 件。無ければ「なし」
- 追加で書くべきテスト: 箇条書き。無ければ「なし」
"""
