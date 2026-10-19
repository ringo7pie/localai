```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    if rows:
        width_check = len(rows[0])
        for row in rows:
            if len(row) != width_check:
                raise ValueError("rows must have the same length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character in grid")

    if not rows or len(rows[0]) == 0:
        return 1
    if not any("." in row for row in rows):
        return 1

    num_rows = len(rows)
    num_cols = len(rows[0])
    # 列数が行数より大きければ転置して、行の長さ(幅)を小さい方にする。
    # ドミノと L トロミノの集合は転置で閉じているので、数は変わらない。
    if num_cols > num_rows:
        rows = ["".join(rows[r][c] for r in range(num_rows)) for c in range(num_cols)]
        num_rows, num_cols = num_cols, num_rows

    width = num_cols
    total = num_rows * width

    def is_open(r: int, c: int) -> bool:
        return 0 <= r < num_rows and 0 <= c < width and rows[r][c] == "."

    shapes = (
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (0, 1), (1, 0)),
        ((0, 0), (0, 1), (1, 1)),
        ((0, 0), (1, 0), (1, 1)),
        ((0, 0), (1, 0), (1, -1)),
    )

    blocked = [False] * total
    pieces: list[list[int]] = [[] for _ in range(total)]
    for pos in range(total):
        r, c = divmod(pos, width)
        if rows[r][c] != ".":
            blocked[pos] = True
            continue
        for shape in shapes:
            ok = True
            mask = 0
            for dr, dc in shape:
                if not is_open(r + dr, c + dc):
                    ok = False
                    break
                mask |= 1 << (dr * width + dc)
            if ok:
                pieces[pos].append(mask)

    # 壊れたプロファイル DP。状態は「今のマス以降の width+1 マスが埋まっているか」のビット列。
    states: dict[int, int] = {0: 1}
    for pos in range(total):
        new_states: dict[int, int] = {}
        get = new_states.get
        piece_list = pieces[pos]
        is_blocked = blocked[pos]
        for mask, ways in states.items():
            if mask & 1 or is_blocked:
                key = mask >> 1
                new_states[key] = get(key, 0) + ways
            else:
                for piece in piece_list:
                    if not (mask & piece):
                        key = (mask | piece) >> 1
                        new_states[key] = get(key, 0) + ways
        states = new_states
        if not states:
            return 0

    return states.get(0, 0)
```
