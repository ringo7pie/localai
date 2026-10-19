```python
def count_tilings(grid: list[str]) -> int:
    rows = len(grid)
    if rows == 0:
        return 1
    cols = len(grid[0])
    for line in grid:
        if not isinstance(line, str) or len(line) != cols:
            raise ValueError("rows must have equal length")
        for ch in line:
            if ch != "." and ch != "#":
                raise ValueError("invalid character")
    if cols == 0:
        return 1
    cells = [[ch == "." for ch in line] for line in grid]
    if not any(any(row) for row in cells):
        return 1
    if cols > rows:
        cells = [[cells[r][c] for r in range(rows)] for c in range(cols)]
        rows, cols = cols, rows
    width = cols
    free = [cells[r][c] for r in range(rows) for c in range(cols)]
    total = rows * cols

    # shapes: (list of (row delta, col delta)) with (0,0) the first cell
    shapes = [
        [(0, 0), (0, 1)],
        [(0, 0), (1, 0)],
        [(0, 0), (0, 1), (1, 0)],
        [(0, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (1, 1)],
        [(0, 0), (1, -1), (1, 0)],
    ]
    shape_bits = []
    for shape in shapes:
        bits = 0
        for dr, dc in shape:
            bits |= 1 << (dr * width + dc)
        shape_bits.append(bits)

    states = {0: 1}
    for index in range(total):
        r, c = divmod(index, width)
        new_states: dict[int, int] = {}
        for mask, ways in states.items():
            if mask & 1:
                key = mask >> 1
                new_states[key] = new_states.get(key, 0) + ways
                continue
            if not free[index]:
                key = mask >> 1
                new_states[key] = new_states.get(key, 0) + ways
                continue
            for shape, bits in zip(shapes, shape_bits):
                ok = True
                for dr, dc in shape:
                    rr = r + dr
                    cc = c + dc
                    if rr >= rows or cc < 0 or cc >= cols or not free[rr * width + cc]:
                        ok = False
                        break
                if not ok or (mask & bits):
                    continue
                key = (mask | bits) >> 1
                new_states[key] = new_states.get(key, 0) + ways
        states = new_states
        if not states:
            return 0
    return states.get(0, 0)
```
