```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    width = len(rows[0]) if rows else 0
    for row in rows:
        if len(row) != width:
            raise ValueError("rows must have the same length")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character in grid")
    if not rows or width == 0:
        return 1

    # Make the width the smaller dimension (<= 10 for the allowed sizes).
    if width > len(rows):
        rows = ["".join(col) for col in zip(*rows)]
    height = len(rows)
    width = len(rows[0])

    def is_free(rr: int, cc: int) -> bool:
        return 0 <= rr < height and 0 <= cc < width and rows[rr][cc] == "."

    # Shapes as offsets (dr, dc) from the first cell in row-major order.
    shapes = [
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (1, -1), (1, 0)),
        ((0, 0), (1, 0), (1, 1)),
        ((0, 0), (0, 1), (1, 1)),
        ((0, 0), (0, 1), (1, 0)),
    ]

    # State: bit i set means cell (p + i) is already covered by an earlier piece.
    dp: dict[int, int] = {0: 1}
    for r in range(height):
        for c in range(width):
            new_dp: dict[int, int] = {}
            get = new_dp.get
            if rows[r][c] == "#":
                for mask, count in dp.items():
                    key = mask >> 1
                    new_dp[key] = get(key, 0) + count
                dp = new_dp
                continue

            piece_masks = []
            for shape in shapes:
                ok = True
                bits = 0
                for dr, dc in shape:
                    if not is_free(r + dr, c + dc):
                        ok = False
                        break
                    bits |= 1 << (dr * width + dc)
                if ok:
                    piece_masks.append(bits)

            for mask, count in dp.items():
                if mask & 1:
                    key = mask >> 1
                    new_dp[key] = get(key, 0) + count
                else:
                    for bits in piece_masks:
                        if not (mask & bits):
                            key = (mask | bits) >> 1
                            new_dp[key] = get(key, 0) + count
            dp = new_dp
            if not dp:
                return 0

    return dp.get(0, 0)
```
