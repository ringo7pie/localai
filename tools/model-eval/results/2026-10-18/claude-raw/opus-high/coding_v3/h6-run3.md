```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list of strings")
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    if len(grid) == 0:
        return 1
    width = len(grid[0])
    for row in grid:
        if len(row) != width:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character in grid")
    height = len(grid)
    if width == 0:
        return 1
    if not any("." in row for row in grid):
        return 1

    rows = grid
    if width > height:
        rows = ["".join(grid[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    total = height * width
    free = [rows[idx // width][idx % width] == "." for idx in range(total)]

    def is_free(row_index: int, col_index: int) -> bool:
        if row_index < 0 or row_index >= height or col_index < 0 or col_index >= width:
            return False
        return free[row_index * width + col_index]

    placements: list[list[int]] = []
    for idx in range(total):
        row_index, col_index = divmod(idx, width)
        options: list[int] = []
        if free[idx]:
            shapes = [
                [(0, 1)],                 # horizontal domino
                [(1, 0)],                 # vertical domino
                [(1, -1), (1, 0)],        # L: missing top-left (first cell is top-right)
                [(1, 0), (1, 1)],         # L: missing top-right
                [(0, 1), (1, 1)],         # L: missing bottom-left
                [(0, 1), (1, 0)],         # L: missing bottom-right
            ]
            for shape in shapes:
                bits = 1
                valid = True
                for d_row, d_col in shape:
                    nr = row_index + d_row
                    nc = col_index + d_col
                    if not is_free(nr, nc):
                        valid = False
                        break
                    offset = d_row * width + d_col
                    bits |= 1 << offset
                if valid:
                    options.append(bits)
        placements.append(options)

    states: dict[int, int] = {0: 1}
    for idx in range(total):
        new_states: dict[int, int] = {}
        get = new_states.get
        options = placements[idx]
        if not free[idx]:
            for mask, count in states.items():
                if mask & 1:
                    continue
                nxt = mask >> 1
                new_states[nxt] = get(nxt, 0) + count
        else:
            for mask, count in states.items():
                if mask & 1:
                    nxt = mask >> 1
                    new_states[nxt] = get(nxt, 0) + count
                else:
                    for bits in options:
                        if mask & bits == 0:
                            nxt = (mask | bits) >> 1
                            new_states[nxt] = get(nxt, 0) + count
        states = new_states
        if not states:
            return 0
    return states.get(0, 0)
```
