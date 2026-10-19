"""H6 count_tilings の参照解（短い辺を幅にした、マスごとの輪郭 DP）。

マスを行優先でたどり、いまのマスから先の W + 2 マスが埋まっているかをビットで持つ。いまのマスが空いていれば、
そのマスを行優先で最初のマスとする駒（ドミノ 2 種・L トロミノ 4 種）を置く。
"""


def count_tilings(grid):
    rows = list(grid)
    if not rows:
        return 1
    width = len(rows[0])
    for row in rows:
        if not isinstance(row, str) or len(row) != width or any(ch not in ".#" for ch in row):
            raise ValueError("bad grid")
    if width == 0:
        return 1
    height = len(rows)
    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height
    free = [[ch == "." for ch in row] for row in rows]

    def ok(r, c):
        return 0 <= r < height and 0 <= c < width and free[r][c]

    states = {0: 1}
    W = width
    for r in range(height):
        for c in range(width):
            nxt = {}
            for mask, ways in states.items():
                if not free[r][c] or mask & 1:
                    key = mask >> 1
                    nxt[key] = nxt.get(key, 0) + ways
                    continue
                options = []
                right = ok(r, c + 1) and not mask & 2
                down = ok(r + 1, c) and not mask >> W & 1
                if right:
                    options.append(1 | 2)
                if down:
                    options.append(1 | 1 << W)
                if down and ok(r + 1, c - 1) and not mask >> (W - 1) & 1:
                    options.append(1 | 1 << (W - 1) | 1 << W)
                if down and ok(r + 1, c + 1) and not mask >> (W + 1) & 1:
                    options.append(1 | 1 << W | 1 << (W + 1))
                if right and ok(r + 1, c + 1) and not mask >> (W + 1) & 1:
                    options.append(1 | 2 | 1 << (W + 1))
                if right and down:
                    options.append(1 | 2 | 1 << W)
                for add in options:
                    key = (mask | add) >> 1
                    nxt[key] = nxt.get(key, 0) + ways
            states = nxt
    return states.get(0, 0)
