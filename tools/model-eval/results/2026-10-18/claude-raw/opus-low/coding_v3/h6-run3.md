```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list")
    if len(grid) == 0:
        return 1
    width0 = None
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("row must be str")
        if width0 is None:
            width0 = len(row)
        elif len(row) != width0:
            raise ValueError("rows differ in length")
        for ch in row:
            if ch not in ".#":
                raise ValueError("bad character")
    rows = [list(row) for row in grid]
    height = len(rows)
    width = width0
    if width == 0:
        return 1
    if width > height:
        rows = [[rows[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height
    blocked = [[ch == "#" for ch in row] for row in rows]
    if not any(not b for row in blocked for b in row):
        return 1

    def free(r, c, mask, off):
        if r < 0 or r >= height or c < 0 or c >= width:
            return False
        if blocked[r][c]:
            return False
        return not (mask >> off) & 1

    states = {0: 1}
    for row_idx in range(height):
        for col in range(width):
            new_states = {}
            for mask, cnt in states.items():
                if blocked[row_idx][col] or (mask & 1):
                    nm = mask >> 1
                    new_states[nm] = new_states.get(nm, 0) + cnt
                    continue
                r1 = free(row_idx, col + 1, mask, 1)
                dn = free(row_idx + 1, col, mask, width)
                dl = free(row_idx + 1, col - 1, mask, width - 1)
                dr = free(row_idx + 1, col + 1, mask, width + 1)
                cands = []
                if r1:
                    cands.append(1 << 1)
                if dn:
                    cands.append(1 << width)
                if r1 and dn:
                    cands.append((1 << 1) | (1 << width))
                if r1 and dr:
                    cands.append((1 << 1) | (1 << (width + 1)))
                if dn and dr:
                    cands.append((1 << width) | (1 << (width + 1)))
                if dn and dl:
                    cands.append((1 << width) | (1 << (width - 1)))
                for add in cands:
                    nm = (mask | add) >> 1
                    new_states[nm] = new_states.get(nm, 0) + cnt
            states = new_states
    return states.get(0, 0)
```
