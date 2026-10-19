```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list of strings")
    if len(grid) == 0:
        return 1
    width = None
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character in grid")
    height = len(grid)
    if width == 0:
        return 1

    rows = [list(row) for row in grid]
    if width > height:
        rows = [[rows[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    if not any(ch == "." for row in rows for ch in row):
        return 1

    blocked = [[ch == "#" for ch in row] for row in rows]

    # Pieces anchored at the first uncovered cell (r, c) in row-major order.
    pieces = [
        [(0, 0), (0, 1)],                 # horizontal domino
        [(0, 0), (1, 0)],                 # vertical domino
        [(0, 0), (0, 1), (1, 0)],         # L missing bottom-right
        [(0, 0), (0, 1), (1, 1)],         # L missing bottom-left
        [(0, 0), (1, 0), (1, 1)],         # L missing top-right
        [(0, 0), (1, -1), (1, 0)],        # L missing top-left
    ]

    states = {0: 1}
    for r in range(height):
        for c in range(width):
            new_states: dict[int, int] = {}
            is_blocked = blocked[r][c]
            for mask, count in states.items():
                if is_blocked or (mask & 1):
                    key = mask >> 1
                    new_states[key] = new_states.get(key, 0) + count
                    continue
                for shape in pieces:
                    bits = 0
                    ok = True
                    for dr, dc in shape:
                        rr = r + dr
                        cc = c + dc
                        if rr >= height or cc < 0 or cc >= width:
                            ok = False
                            break
                        if blocked[rr][cc]:
                            ok = False
                            break
                        offset = dr * width + dc
                        bit = 1 << offset
                        if mask & bit:
                            ok = False
                            break
                        bits |= bit
                    if not ok:
                        continue
                    key = (mask | bits) >> 1
                    new_states[key] = new_states.get(key, 0) + count
            states = new_states
            if not states:
                return 0
    return states.get(0, 0)
```
