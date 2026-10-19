```python
def count_tilings(grid: list[str]) -> int:
    rows = list(grid)
    height = len(rows)
    if height == 0:
        return 1

    width = None
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("rows must have the same length")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError("invalid character in grid")

    if width == 0:
        return 1

    cells = [[ch == "." for ch in row] for row in rows]
    if not any(any(line) for line in cells):
        return 1

    # 幅が小さい方になるように転置する（状態数は 2^(幅+1) で抑える）
    if width > height:
        cells = [[cells[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height

    def free(r: int, c: int) -> bool:
        return 0 <= r < height and 0 <= c < width and cells[r][c]

    # 状態: 現在のマス（bit 0）から、その真下のマス（bit width）までの
    # width + 1 マスぶんが、すでに駒で覆われているかどうか。
    # 駒は「行優先で最初に来るマス」を現在のマスとして置く。
    dp = {0: 1}
    for r in range(height):
        for c in range(width):
            if not cells[r][c]:
                dp = {mask >> 1: count for mask, count in dp.items()}
                continue

            right = free(r, c + 1)
            down = free(r + 1, c)
            down_right = free(r + 1, c + 1)
            down_left = free(r + 1, c - 1)

            options = []
            if right:
                options.append(1 | 2)  # 横ドミノ
            if down:
                options.append(1 | (1 << width))  # 縦ドミノ
            if down and down_right:
                options.append(1 | (1 << width) | (1 << (width + 1)))
            if right and down_right:
                options.append(1 | 2 | (1 << (width + 1)))
            if right and down:
                options.append(1 | 2 | (1 << width))
            if down and down_left:
                options.append(1 | (1 << (width - 1)) | (1 << width))

            nxt = {}
            get = nxt.get
            for mask, count in dp.items():
                if mask & 1:
                    key = mask >> 1
                    nxt[key] = get(key, 0) + count
                else:
                    for add in options:
                        if not (mask & add):
                            key = (mask | add) >> 1
                            nxt[key] = get(key, 0) + count
            dp = nxt
            if not dp:
                return 0

    return dp.get(0, 0)
```
