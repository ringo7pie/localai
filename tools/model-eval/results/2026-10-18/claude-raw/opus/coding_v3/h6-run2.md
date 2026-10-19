```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    if not rows:
        return 1
    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError(f"invalid character: {ch!r}")
    height = len(rows)
    if width == 0:
        return 1

    free = [[ch == "." for ch in row] for row in rows]
    if not any(any(row) for row in free):
        return 1

    # 幅を短い方の辺にする（転置しても駒の集合は閉じているので数は変わらない）
    if width > height:
        free = [[free[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    total = height * width
    is_free = [free[p // width][p % width] for p in range(total)]

    def cell_ok(r: int, c: int) -> bool:
        return 0 <= r < height and 0 <= c < width and free[r][c]

    # 行優先の順で最初のマスを (0, 0) とした駒の形
    shapes = (
        ((0, 0), (0, 1)),            # 横ドミノ
        ((0, 0), (1, 0)),            # 縦ドミノ
        ((0, 0), (0, 1), (1, 0)),    # L: 右下が欠け
        ((0, 0), (0, 1), (1, 1)),    # L: 左下が欠け
        ((0, 0), (1, 0), (1, 1)),    # L: 右上が欠け
        ((0, 0), (1, -1), (1, 0)),   # L: 左上が欠け
    )

    pieces_at = []
    for p in range(total):
        r, c = divmod(p, width)
        masks = []
        if is_free[p]:
            for shape in shapes:
                if all(cell_ok(r + dr, c + dc) for dr, dc in shape):
                    bits = 0
                    for dr, dc in shape:
                        bits |= 1 << (dr * width + dc)
                    masks.append(bits)
        pieces_at.append(tuple(masks))

    # 状態: ビット i が立っていれば、位置 p + i のマスは既に覆われている
    states = {0: 1}
    for p in range(total):
        nxt: dict[int, int] = {}
        get = nxt.get
        if not is_free[p]:
            for mask, ways in states.items():
                key = mask >> 1
                nxt[key] = get(key, 0) + ways
        else:
            pieces = pieces_at[p]
            for mask, ways in states.items():
                if mask & 1:
                    key = mask >> 1
                    nxt[key] = get(key, 0) + ways
                else:
                    for piece in pieces:
                        if not (mask & piece):
                            key = (mask | piece) >> 1
                            nxt[key] = get(key, 0) + ways
        states = nxt
        if not states:
            return 0
    return states.get(0, 0)
```
