```python
_PIECES = (
    # 各駒は「行優先で最初のマス」を (0, 0) に置いたときの (行の差, 列の差) の並び。
    ((0, 0), (0, 1)),                  # 横ドミノ
    ((0, 0), (1, 0)),                  # 縦ドミノ
    ((0, 0), (0, 1), (1, 0)),          # L: 右下を除く
    ((0, 0), (0, 1), (1, 1)),          # L: 左下を除く
    ((0, 0), (1, 0), (1, 1)),          # L: 右上を除く
    ((0, 0), (1, -1), (1, 0)),         # L: 左上を除く（最初のマスは右上）
)


def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    if rows:
        width_first = len(rows[0])
        for row in rows:
            if len(row) != width_first:
                raise ValueError("rows must have the same length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character in grid")
    if not rows or len(rows[0]) == 0:
        return 1

    free = [[ch == "." for ch in row] for row in rows]
    # 列数を小さい方にそろえる（駒の集合は転置で閉じているので数は変わらない）
    if len(free[0]) > len(free):
        free = [list(col) for col in zip(*free)]
    height = len(free)
    width = len(free[0])

    total = height * width
    blocked = [False] * total
    for row_index in range(height):
        for col_index in range(width):
            if not free[row_index][col_index]:
                blocked[row_index * width + col_index] = True

    # 各マスを最初のマスとして置ける駒を、窓のビット列（bit i = マス p+i）で前計算する
    piece_bits: list[list[int]] = []
    for row_index in range(height):
        for col_index in range(width):
            position = row_index * width + col_index
            options: list[int] = []
            if not blocked[position]:
                for piece in _PIECES:
                    bits = 0
                    ok = True
                    for d_row, d_col in piece:
                        new_row = row_index + d_row
                        new_col = col_index + d_col
                        if new_row >= height or new_col < 0 or new_col >= width:
                            ok = False
                            break
                        if blocked[new_row * width + new_col]:
                            ok = False
                            break
                        bits |= 1 << (d_row * width + d_col)
                    if ok:
                        options.append(bits)
            piece_bits.append(options)

    dp: dict[int, int] = {0: 1}
    for position in range(total):
        options = piece_bits[position]
        new_dp: dict[int, int] = {}
        get = new_dp.get
        if blocked[position]:
            for mask, count in dp.items():
                key = mask >> 1
                new_dp[key] = get(key, 0) + count
        else:
            for mask, count in dp.items():
                if mask & 1:
                    key = mask >> 1
                    new_dp[key] = get(key, 0) + count
                else:
                    for bits in options:
                        if not (mask & bits):
                            key = (mask | bits) >> 1
                            new_dp[key] = get(key, 0) + count
        dp = new_dp
        if not dp:
            return 0
    return dp.get(0, 0)
```
