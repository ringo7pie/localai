```python
from collections import defaultdict

_SHAPES = (
    ((0, 1),),
    ((1, 0),),
    ((0, 1), (1, 0)),
    ((0, 1), (1, 1)),
    ((1, 0), (1, 1)),
    ((1, -1), (1, 0)),
)


def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list of strings")
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("rows must be strings")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character")
    height = len(grid)
    if height == 0:
        return 1
    width = len(grid[0])
    for row in grid:
        if len(row) != width:
            raise ValueError("rows have different lengths")
    if width == 0:
        return 1
    if not any("." in row for row in grid):
        return 1
    if width > height:
        grid = ["".join(grid[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height
    free = [[ch == "." for ch in row] for row in grid]

    states = {0: 1}
    for r in range(height):
        for c in range(width):
            new_states = defaultdict(int)
            cell_free = free[r][c]
            for mask, cnt in states.items():
                if (mask & 1) or not cell_free:
                    new_states[mask >> 1] += cnt
                    continue
                for shape in _SHAPES:
                    bits = 1
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
                        new_states[(mask | bits) >> 1] += cnt
            states = new_states
            if not states:
                return 0
    return states.get(0, 0)
```
