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
                raise ValueError("invalid character")
    if width == 0:
        return 1

    rows = list(grid)
    height = len(rows)
    if width > height:
        rows = ["".join(rows[r][c] for r in range(height)) for c in range(width)]
        height, width = width, height

    full = (1 << width) - 1
    blocked = []
    for row in rows:
        mask = 0
        for c, ch in enumerate(row):
            if ch == "#":
                mask |= 1 << c
        blocked.append(mask)

    if all(mask == full for mask in blocked):
        return 1

    # state: dict mapping (cur | nxt << width) -> count
    states = {blocked[0]: 1}  # nxt part filled in at row start
    for r in range(height):
        nxt_init = blocked[r + 1] if r + 1 < height else full
        cur_states = {}
        for cur, cnt in states.items():
            key = cur | (nxt_init << width)
            cur_states[key] = cur_states.get(key, 0) + cnt
        for c in range(width):
            bit = 1 << c
            new_states = {}
            for key, cnt in cur_states.items():
                cur = key & full
                nxt = key >> width
                if cur & bit:
                    new_states[key] = new_states.get(key, 0) + cnt
                    continue
                has_right = c + 1 < width and not (cur & (bit << 1))
                right = bit << 1
                nxt_c_free = not (nxt & bit)
                nxt_r_free = c + 1 < width and not (nxt & (bit << 1))
                nxt_l_free = c >= 1 and not (nxt & (bit >> 1))

                def add(new_cur, new_nxt):
                    k = new_cur | (new_nxt << width)
                    new_states[k] = new_states.get(k, 0) + cnt

                # horizontal domino
                if has_right:
                    add(cur | bit | right, nxt)
                # vertical domino
                if nxt_c_free:
                    add(cur | bit, nxt | bit)
                # L: (r,c),(r,c+1),(r+1,c)
                if has_right and nxt_c_free:
                    add(cur | bit | right, nxt | bit)
                # L: (r,c),(r,c+1),(r+1,c+1)
                if has_right and nxt_r_free:
                    add(cur | bit | right, nxt | (bit << 1))
                # L: (r,c),(r+1,c),(r+1,c+1)
                if nxt_c_free and nxt_r_free:
                    add(cur | bit, nxt | bit | (bit << 1))
                # L: (r,c),(r+1,c-1),(r+1,c)
                if nxt_c_free and nxt_l_free:
                    add(cur | bit, nxt | bit | (bit >> 1))
            cur_states = new_states
            if not cur_states:
                return 0
        states = {}
        for key, cnt in cur_states.items():
            cur = key & full
            if cur != full:
                continue
            nxt = key >> width
            states[nxt] = states.get(nxt, 0) + cnt
        if not states:
            return 0

    return sum(cnt for nxt, cnt in states.items() if nxt == full)
```
