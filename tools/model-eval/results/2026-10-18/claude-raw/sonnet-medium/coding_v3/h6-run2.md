```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        width0 = len(rows[0])
    else:
        width0 = 0
    for row in rows:
        if len(row) != width0:
            raise ValueError("rows have different lengths")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character")
    height = len(rows)
    width = width0
    if height == 0 or width == 0:
        return 1
    if not any("." in row for row in rows):
        return 1

    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    blocked = []
    for r in range(height):
        for c in range(width):
            blocked.append(rows[r][c] == "#")

    pieces = [
        [(0, 1)],
        [(1, 0)],
        [(0, 1), (1, 0)],
        [(0, 1), (1, 1)],
        [(1, 0), (1, 1)],
        [(1, -1), (1, 0)],
    ]

    dp = {0: 1}
    for r in range(height):
        for c in range(width):
            pos = r * width + c
            new_dp = {}
            if blocked[pos]:
                for mask, ways in dp.items():
                    # bit 0 is never set for a blocked cell
                    key = mask >> 1
                    new_dp[key] = new_dp.get(key, 0) + ways
                dp = new_dp
                continue
            for mask, ways in dp.items():
                if mask & 1:
                    key = mask >> 1
                    new_dp[key] = new_dp.get(key, 0) + ways
                    continue
                for piece in pieces:
                    new_mask = mask | 1
                    ok = True
                    for dr, dc in piece:
                        rr = r + dr
                        cc = c + dc
                        if rr >= height or cc < 0 or cc >= width:
                            ok = False
                            break
                        target = rr * width + cc
                        if blocked[target]:
                            ok = False
                            break
                        bit = 1 << (target - pos)
                        if new_mask & bit:
                            ok = False
                            break
                        new_mask |= bit
                    if ok:
                        key = new_mask >> 1
                        new_dp[key] = new_dp.get(key, 0) + ways
            dp = new_dp
            if not dp:
                return 0
    return dp.get(0, 0)
```
