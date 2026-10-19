```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list of strings")
    if len(grid) == 0:
        return 1
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
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

    # Make the number of columns the smaller dimension.
    if width > height:
        grid = ["".join(grid[row_index][col_index] for row_index in range(height))
                for col_index in range(width)]
        height, width = width, height

    free = [[ch == "." for ch in row] for row in grid]
    if not any(any(row) for row in free):
        return 1

    # Shapes given as offsets (dr, dc) relative to the anchor cell (the first
    # cell of the piece in row-major order), excluding the anchor itself.
    shapes = [
        [(0, 1)],                 # horizontal domino
        [(1, 0)],                 # vertical domino
        [(0, 1), (1, 0)],         # L: missing bottom-right
        [(0, 1), (1, 1)],         # L: missing bottom-left
        [(1, 0), (1, 1)],         # L: missing top-right
        [(1, -1), (1, 0)],        # L: missing top-left
    ]

    dp: dict[int, int] = {0: 1}
    for row_index in range(height):
        for col_index in range(width):
            new_dp: dict[int, int] = {}
            cell_free = free[row_index][col_index]
            for mask, ways in dp.items():
                if not cell_free or (mask & 1):
                    # Blocked cell (never occupied by placements) or already covered.
                    key = mask >> 1
                    new_dp[key] = new_dp.get(key, 0) + ways
                    continue
                for shape in shapes:
                    added = 1
                    ok = True
                    for d_row, d_col in shape:
                        target_row = row_index + d_row
                        target_col = col_index + d_col
                        if target_row >= height or target_col < 0 or target_col >= width:
                            ok = False
                            break
                        if not free[target_row][target_col]:
                            ok = False
                            break
                        bit = 1 << (d_row * width + d_col)
                        if mask & bit:
                            ok = False
                            break
                        added |= bit
                    if not ok:
                        continue
                    key = (mask | added) >> 1
                    new_dp[key] = new_dp.get(key, 0) + ways
            dp = new_dp
            if not dp:
                return 0
    return dp.get(0, 0)
```
