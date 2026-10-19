```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list")
    if not grid:
        return 1
    width0 = None
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("rows must be strings")
        if width0 is None:
            width0 = len(row)
        elif len(row) != width0:
            raise ValueError("rows must have equal length")
        for ch in row:
            if ch not in ".#":
                raise ValueError("invalid character")
    if width0 == 0:
        return 1
    rows = [list(row) for row in grid]
    height = len(rows)
    width = width0
    if width > height:
        rows = [[rows[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    if not any(ch == "." for row in rows for ch in row):
        return 1

    total = height * width
    blocked = [rows[idx // width][idx % width] == "#" for idx in range(total)]

    def free(mask: int, pos: int, q: int) -> bool:
        if q >= total:
            return False
        if blocked[q]:
            return False
        return not (mask >> (q - pos)) & 1

    dp = {0: 1}
    for pos in range(total):
        r = pos // width
        c = pos % width
        has_right = c + 1 < width
        has_left = c >= 1
        has_down = r + 1 < height
        ndp: dict[int, int] = {}
        for mask, cnt in dp.items():
            if (mask & 1) or blocked[pos]:
                nm = mask >> 1
                ndp[nm] = ndp.get(nm, 0) + cnt
                continue
            right = pos + 1
            down = pos + width
            down_right = pos + width + 1
            down_left = pos + width - 1
            options = []
            right_free = has_right and free(mask, pos, right)
            down_free = has_down and free(mask, pos, down)
            if right_free:
                options.append((right,))
            if down_free:
                options.append((down,))
            if right_free and down_free:
                options.append((right, down))
            if right_free and has_down and free(mask, pos, down_right):
                options.append((right, down_right))
            if down_free and has_right and free(mask, pos, down_right):
                options.append((down, down_right))
            if down_free and has_left and free(mask, pos, down_left):
                options.append((down_left, down))
            for cells in options:
                nm = mask | 1
                for q in cells:
                    nm |= 1 << (q - pos)
                nm >>= 1
                ndp[nm] = ndp.get(nm, 0) + cnt
        dp = ndp
    return dp.get(0, 0)
```
