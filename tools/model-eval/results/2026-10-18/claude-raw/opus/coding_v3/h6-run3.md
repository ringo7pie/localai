```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    width = len(rows[0]) if rows else 0
    for row in rows:
        if len(row) != width:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character in grid")
    height = len(rows)

    if not any("." in row for row in rows):
        return 1

    # 幅を小さい方にそろえる（ドミノと L トロミノの集合は転置で閉じている）
    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    free = [[ch == "." for ch in row] for row in rows]

    # 各駒の、行優先で最初のマスを基準にした相対位置
    shapes = (
        ((0, 0), (0, 1)),            # 横ドミノ
        ((0, 0), (1, 0)),            # 縦ドミノ
        ((0, 0), (1, -1), (1, 0)),   # L: 左上が欠け
        ((0, 0), (1, 0), (1, 1)),    # L: 右上が欠け
        ((0, 0), (0, 1), (1, 1)),    # L: 左下が欠け
        ((0, 0), (0, 1), (1, 0)),    # L: 右下が欠け
    )

    size = 1 << (width + 1)
    states = [0] * size
    states[0] = 1

    for r in range(height):
        for c in range(width):
            new_states = [0] * size
            if not free[r][c]:
                for mask in range(size):
                    count = states[mask]
                    if count:
                        new_states[mask >> 1] += count
            else:
                pieces = []
                for shape in shapes:
                    bits = 0
                    ok = True
                    for dr, dc in shape:
                        rr = r + dr
                        cc = c + dc
                        if rr >= height or cc < 0 or cc >= width or not free[rr][cc]:
                            ok = False
                            break
                        bits |= 1 << (dr * width + dc)
                    if ok:
                        pieces.append(bits)
                for mask in range(size):
                    count = states[mask]
                    if not count:
                        continue
                    if mask & 1:
                        new_states[mask >> 1] += count
                    else:
                        for bits in pieces:
                            if not (mask & bits):
                                new_states[(mask | bits) >> 1] += count
            states = new_states

    return states[0]
```
