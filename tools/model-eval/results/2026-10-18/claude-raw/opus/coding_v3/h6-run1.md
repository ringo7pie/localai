```python
from collections import defaultdict


def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, (list, tuple)):
        raise ValueError("grid must be a list of strings")
    rows = list(grid)
    if not rows:
        return 1
    for row in rows:
        if not isinstance(row, str):
            raise ValueError("each row must be a string")
    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise ValueError("rows must have the same length")
        for ch in row:
            if ch != "." and ch != "#":
                raise ValueError(f"invalid character: {ch!r}")
    height = len(rows)
    if width == 0:
        return 1

    # 列数を小さい方にそろえる（転置しても駒の集合は変わらない）
    if width > height:
        rows = ["".join(row[col] for row in rows) for col in range(width)]
        height, width = width, height

    free_count = sum(row.count(".") for row in rows)
    if free_count == 0:
        return 1
    if free_count == 1:
        return 0

    full = (1 << width) - 1
    blocked = []
    for row in rows:
        mask = 0
        for col, ch in enumerate(row):
            if ch == "#":
                mask |= 1 << col
        blocked.append(mask)

    # 状態: 下位 width ビット = 現在の行の埋まり、上位 width ビット = 次の行の埋まり
    states = {0: 1}
    for r in range(height):
        blk_cur = blocked[r]
        blk_nxt = blocked[r + 1] if r + 1 < height else full
        blk_all = blk_cur | (blk_nxt << width)
        for c in range(width):
            bit = 1 << c
            if blk_cur & bit:
                continue
            down = bit << width
            candidates = []
            if c + 1 < width:
                right = bit << 1
                candidates.append(right)                    # 横ドミノ
                candidates.append(right | down)             # L: (r,c),(r,c+1),(r+1,c)
                candidates.append(right | (down << 1))      # L: (r,c),(r,c+1),(r+1,c+1)
                candidates.append(down | (down << 1))       # L: (r,c),(r+1,c),(r+1,c+1)
            candidates.append(down)                         # 縦ドミノ
            if c >= 1:
                candidates.append(down | (down >> 1))       # L: (r,c),(r+1,c-1),(r+1,c)
            pieces = tuple(m for m in candidates if not m & blk_all)

            new_states = defaultdict(int)
            for st, cnt in states.items():
                if st & bit:
                    new_states[st ^ bit] += cnt
                else:
                    for m in pieces:
                        if not st & m:
                            new_states[st | m] += cnt
            if not new_states:
                return 0
            states = new_states
        next_states = {}
        for st, cnt in states.items():
            if st & full:
                continue
            key = st >> width
            next_states[key] = next_states.get(key, 0) + cnt
        states = next_states
        if not states:
            return 0
    return states.get(0, 0)
```
