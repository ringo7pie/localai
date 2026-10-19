```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        width0 = len(rows[0])
        for row in rows:
            if len(row) != width0:
                raise ValueError("rows differ in length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character")
    height = len(rows)
    width = len(rows[0]) if rows else 0
    if height == 0 or width == 0:
        return 1
    if not any("." in row for row in rows):
        return 1
    cells = [[ch == "." for ch in row] for row in rows]
    if width > height:
        cells = [[cells[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    shapes = [
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (0, 1), (1, 0)),
        ((0, 0), (0, 1), (1, 1)),
        ((0, 0), (1, 0), (1, 1)),
        ((0, 0), (1, -1), (1, 0)),
    ]

    states = {0: 1}
    for row in range(height):
        for col in range(width):
            new_states: dict[int, int] = {}
            free = cells[row][col]
            for mask, count in states.items():
                if not free:
                    if mask & 1:
                        continue
                    key = mask >> 1
                    new_states[key] = new_states.get(key, 0) + count
                    continue
                if mask & 1:
                    key = mask >> 1
                    new_states[key] = new_states.get(key, 0) + count
                    continue
                for shape in shapes:
                    new_mask = mask
                    ok = True
                    for dr, dc in shape:
                        rr = row + dr
                        cc = col + dc
                        if rr >= height or cc < 0 or cc >= width or not cells[rr][cc]:
                            ok = False
                            break
                        bit = 1 << (dr * width + dc)
                        if new_mask & bit:
                            ok = False
                            break
                        new_mask |= bit
                    if ok:
                        key = new_mask >> 1
                        new_states[key] = new_states.get(key, 0) + count
            states = new_states
    return states.get(0, 0)
```
