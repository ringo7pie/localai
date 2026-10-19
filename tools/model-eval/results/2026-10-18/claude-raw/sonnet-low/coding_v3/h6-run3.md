```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        length = len(rows[0])
        for row in rows:
            if not isinstance(row, str) or len(row) != length:
                raise ValueError("rows must have equal length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character")
    height = len(rows)
    width = len(rows[0]) if rows else 0
    if height == 0 or width == 0:
        return 1
    free = [[ch == "." for ch in row] for row in rows]
    if not any(any(line) for line in free):
        return 1
    if width > height:
        free = [[free[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    shapes = [
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (0, 1), (1, 0)),
        ((0, 0), (0, 1), (1, 1)),
        ((0, 0), (1, 0), (1, 1)),
        ((0, 0), (1, -1), (1, 0)),
    ]

    dp = {0: 1}
    for r in range(height):
        for c in range(width):
            new = {}
            is_free = free[r][c]
            for mask, ways in dp.items():
                if mask & 1:
                    if not is_free:
                        continue
                    key = mask >> 1
                    new[key] = new.get(key, 0) + ways
                    continue
                if not is_free:
                    key = mask >> 1
                    new[key] = new.get(key, 0) + ways
                    continue
                for shape in shapes:
                    bits = 0
                    ok = True
                    for dr, dc in shape:
                        rr = r + dr
                        cc = c + dc
                        if rr >= height or cc < 0 or cc >= width or not free[rr][cc]:
                            ok = False
                            break
                        bit = 1 << (dr * width + dc)
                        if mask & bit:
                            ok = False
                            break
                        bits |= bit
                    if ok:
                        key = (mask | bits) >> 1
                        new[key] = new.get(key, 0) + ways
            dp = new
    return dp.get(0, 0)
```
