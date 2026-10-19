```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    if rows:
        width0 = len(rows[0])
        for row in rows:
            if len(row) != width0:
                raise ValueError("rows have different lengths")
            for ch in row:
                if ch != "." and ch != "#":
                    raise ValueError("invalid character")
    height = len(rows)
    width = len(rows[0]) if rows else 0
    if height == 0 or width == 0:
        return 1

    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    blocked = [rows[r][c] == "#" for r in range(height) for c in range(width)]
    total = height * width

    dp = {0: 1}
    for pos in range(total):
        row, col = divmod(pos, width)
        has_right = col + 1 < width
        has_down = row + 1 < height
        has_left = col >= 1
        nxt = {}

        if blocked[pos]:
            for mask, ways in dp.items():
                if mask & 1:
                    continue
                key = mask >> 1
                nxt[key] = nxt.get(key, 0) + ways
            dp = nxt
            continue

        # Candidate pieces: offset lists with feasibility conditions.
        pieces = []
        if has_right:
            pieces.append((1,))
        if has_down:
            pieces.append((width,))
        if has_right and has_down:
            pieces.append((1, width))
            pieces.append((1, width + 1))
            pieces.append((width, width + 1))
        if has_left and has_down:
            pieces.append((width - 1, width))

        valid = []
        for offsets in pieces:
            bits = 1
            ok = True
            for off in offsets:
                if blocked[pos + off]:
                    ok = False
                    break
                bits |= 1 << off
            if ok:
                valid.append(bits)

        for mask, ways in dp.items():
            if mask & 1:
                key = mask >> 1
                nxt[key] = nxt.get(key, 0) + ways
                continue
            for bits in valid:
                if mask & bits:
                    continue
                key = (mask | bits) >> 1
                nxt[key] = nxt.get(key, 0) + ways
        dp = nxt

    return dp.get(0, 0)
```
