```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list")
    if len(grid) == 0:
        return 1
    width = None
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("row must be str")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("rows differ in length")
        for ch in row:
            if ch not in ".#":
                raise ValueError("invalid character")
    rows = len(grid)
    cols = width
    if cols == 0:
        return 1
    cells = [[ch == "#" for ch in row] for row in grid]
    if cols > rows:
        cells = [[cells[r][c] for r in range(rows)] for c in range(cols)]
        rows, cols = cols, rows
    if not any(not b for row in cells for b in row):
        return 1

    def free(r, c):
        return 0 <= r < rows and 0 <= c < cols and not cells[r][c]

    shapes = [
        [(0, 0), (0, 1)],
        [(0, 0), (1, 0)],
        [(0, 0), (0, 1), (1, 0)],
        [(0, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (1, 1)],
        [(0, 0), (1, -1), (1, 0)],
    ]
    states = {0: 1}
    for r in range(rows):
        for c in range(cols):
            new_states = {}
            blocked = cells[r][c]
            for mask, ways in states.items():
                if blocked or (mask & 1):
                    key = mask >> 1
                    new_states[key] = new_states.get(key, 0) + ways
                    continue
                for shape in shapes:
                    add = 0
                    ok = True
                    for dr, dc in shape:
                        rr, cc = r + dr, c + dc
                        if not free(rr, cc):
                            ok = False
                            break
                        bit = 1 << (dr * cols + dc)
                        if mask & bit:
                            ok = False
                            break
                        add |= bit
                    if ok:
                        key = (mask | add) >> 1
                        new_states[key] = new_states.get(key, 0) + ways
            states = new_states
            if not states:
                return 0
    return states.get(0, 0)
```
