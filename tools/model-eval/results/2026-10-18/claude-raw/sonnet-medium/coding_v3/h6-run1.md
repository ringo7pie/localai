```python
def count_tilings(grid: list[str]) -> int:
    rows = len(grid)
    if rows == 0:
        return 1
    cols = len(grid[0])
    for row in grid:
        if len(row) != cols:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character")
    if cols == 0:
        return 1

    cells = [[ch == "." for ch in row] for row in grid]
    if rows < cols:
        cells = [[cells[r][c] for r in range(rows)] for c in range(cols)]
        rows, cols = cols, rows
    # now cols <= rows (cols is the smaller dimension)

    # placements anchored at the first cell (row-major order) of the piece
    placements = [
        [(0, 0), (0, 1)],
        [(0, 0), (1, 0)],
        [(0, 0), (0, 1), (1, 0)],
        [(0, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (1, 1)],
        [(0, 0), (1, -1), (1, 0)],
    ]

    dp = {0: 1}
    for r in range(rows):
        for c in range(cols):
            free = cells[r][c]
            valid = []
            if free:
                for piece in placements:
                    ok = True
                    bits = 0
                    for dr, dc in piece:
                        rr = r + dr
                        cc = c + dc
                        if rr >= rows or cc < 0 or cc >= cols or not cells[rr][cc]:
                            ok = False
                            break
                        bits |= 1 << (dr * cols + dc)
                    if ok:
                        valid.append(bits)
            new_dp = {}
            get = new_dp.get
            for mask, ways in dp.items():
                if mask & 1:
                    key = mask >> 1
                    new_dp[key] = get(key, 0) + ways
                elif not free:
                    key = mask >> 1
                    new_dp[key] = get(key, 0) + ways
                else:
                    for bits in valid:
                        if mask & bits:
                            continue
                        key = (mask | bits) >> 1
                        new_dp[key] = get(key, 0) + ways
            dp = new_dp
            if not dp:
                return 0
    return dp.get(0, 0)
```
