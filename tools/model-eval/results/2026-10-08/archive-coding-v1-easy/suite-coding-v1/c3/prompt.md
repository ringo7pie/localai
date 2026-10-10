## 問題 C3: 区間の併合

関数 `merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]` を書いてください。

- `intervals` の各要素は整数の組 `(start, end)` で、`start` 以上 `end` 以下の閉区間を表す。
- 重なる区間と、端が接する区間（一方の `end` と他方の `start` が等しい）を 1 つにまとめ、`start` の昇順に並べた「タプルのリスト」を返す。
- 入力は並んでいるとは限らない。入力のリストを書き換えてはいけない。
- 空のリストには空のリストを返す。
- `start > end` の要素が 1 つでもあれば `ValueError` を送出する。
- 要素数は最大 100,000。

例:
- `merge_intervals([(1, 3), (2, 6), (8, 10), (15, 18)])` → `[(1, 6), (8, 10), (15, 18)]`
- `merge_intervals([(1, 4), (4, 5)])` → `[(1, 5)]`
