```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        width0 = len(rows[0])
        for row in rows:
            if not isinstance(row, str) or len(row) != width0:
                raise ValueError("rows must have the same length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character")
    height = len(rows)
    width = len(rows[0]) if rows else 0
    if height == 0 or width == 0:
        return 1

    # make the width the smaller dimension
    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    free = [[ch == "." for ch in row] for row in rows]

    # piece shapes as offsets (dr, dc) from the first cell in row-major order
    shapes = [
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (0, 1), (1, 0)),
        ((0, 0), (0, 1), (1, 1)),
        ((0, 0), (1, 0), (1, 1)),
        ((0, 0), (1, -1), (1, 0)),
    ]

    dp = {0: 1}
    for row in range(height):
        for col in range(width):
            # piece masks valid on the grid for the anchor at (row, col)
            piece_masks = []
            if free[row][col]:
                for shape in shapes:
                    mask = 0
                    ok = True
                    for dr, dc in shape:
                        rr = row + dr
                        cc = col + dc
                        if rr >= height or cc < 0 or cc >= width or not free[rr][cc]:
                            ok = False
                            break
                        mask |= 1 << (dr * width + dc)
                    if ok:
                        piece_masks.append(mask)
            new_dp = {}
            get = new_dp.get
            for state, ways in dp.items():
                if state & 1:
                    key = state >> 1
                    new_dp[key] = get(key, 0) + ways
                elif not free[row][col]:
                    key = state >> 1
                    new_dp[key] = get(key, 0) + ways
                else:
                    for mask in piece_masks:
                        if state & mask:
                            continue
                        key = (state | mask) >> 1
                        new_dp[key] = get(key, 0) + ways
            dp = new_dp
    return dp.get(0, 0)
```
