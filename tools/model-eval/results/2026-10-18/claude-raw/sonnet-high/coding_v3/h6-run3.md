```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        width0 = len(rows[0])
        for row in rows:
            if not isinstance(row, str) or len(row) != width0:
                raise ValueError("rows must be strings of equal length")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character")
    height = len(rows)
    width = len(rows[0]) if rows else 0

    free_count = sum(row.count(".") for row in rows)
    if free_count == 0:
        return 1
    if free_count % 1 != 0:
        return 0

    # 幅（プロファイルの長さ）が小さくなるように転置する
    cells = [[ch == "." for ch in row] for row in rows]
    if width > height:
        cells = [[cells[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    pieces = [
        [(0, 0), (0, 1)],
        [(0, 0), (1, 0)],
        [(0, 0), (0, 1), (1, 0)],
        [(0, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (1, 1)],
        [(0, 0), (1, -1), (1, 0)],
    ]

    # 各セルで置ける駒を前計算する: (駒が占める相対ビットの mask)
    dp = {0: 1}
    for row in range(height):
        for col in range(width):
            pos_options = []
            if cells[row][col]:
                for piece in pieces:
                    bits = 0
                    valid = True
                    for d_row, d_col in piece:
                        n_row = row + d_row
                        n_col = col + d_col
                        if (
                            n_row >= height
                            or n_col < 0
                            or n_col >= width
                            or not cells[n_row][n_col]
                        ):
                            valid = False
                            break
                        bits |= 1 << (d_row * width + d_col)
                    if valid:
                        pos_options.append(bits)
            is_free = cells[row][col]
            new_dp = {}
            for mask, ways in dp.items():
                if mask & 1:
                    new_mask = mask >> 1
                    new_dp[new_mask] = new_dp.get(new_mask, 0) + ways
                elif not is_free:
                    new_mask = mask >> 1
                    new_dp[new_mask] = new_dp.get(new_mask, 0) + ways
                else:
                    for bits in pos_options:
                        if mask & bits:
                            continue
                        new_mask = (mask | bits) >> 1
                        new_dp[new_mask] = new_dp.get(new_mask, 0) + ways
            dp = new_dp
            if not dp:
                return 0
    return dp.get(0, 0)
```
