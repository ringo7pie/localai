"""H6 のオラクル 2 つ（参照解とは別の作り）。

- count_tilings_brute: 敷き詰めを 1 つずつ数える素朴な探索（小さい盤面だけ）
- count_tilings_memo: 盤面全体の埋まり具合を集合で持ち、最初の空きマスを覆う駒を全部試す再帰をメモ化（中くらいの盤面）
"""

from functools import lru_cache

SHAPES = (
    ((0, 0), (0, 1)), ((0, 0), (1, 0)),
    ((0, 0), (1, 0), (1, 1)), ((0, 0), (0, 1), (1, 1)), ((0, 0), (0, 1), (1, 0)), ((0, 1), (1, 0), (1, 1)),
)


def _cells(grid):
    if not grid:
        return frozenset()
    width = len(grid[0])
    for row in grid:
        if len(row) != width or any(ch not in ".#" for ch in row):
            raise ValueError
    return frozenset((r, c) for r, row in enumerate(grid) for c, ch in enumerate(row) if ch == ".")


def _placements(first, empty):
    """first を行優先で最初のマスとして覆う駒の置き方。"""

    r, c = first
    out = []
    for shape in SHAPES:
        top = min(shape)
        cells = frozenset((r + dr - top[0], c + dc - top[1]) for dr, dc in shape)
        if cells <= empty:
            out.append(cells)
    return out


def count_tilings_brute(grid):
    empty = set(_cells(grid))

    def go():
        if not empty:
            return 1
        first = min(empty)
        total = 0
        for piece in _placements(first, frozenset(empty)):
            empty.difference_update(piece)
            total += go()
            empty.update(piece)
        return total

    return go()


def count_tilings_memo(grid):
    @lru_cache(maxsize=None)
    def go(empty):
        if not empty:
            return 1
        first = min(empty)
        return sum(go(empty - piece) for piece in _placements(first, empty))

    return go(_cells(grid))
