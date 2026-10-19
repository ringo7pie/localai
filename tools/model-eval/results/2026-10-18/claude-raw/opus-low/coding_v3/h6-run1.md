```python
def count_tilings(grid: list[str]) -> int:
    if not isinstance(grid, list):
        raise ValueError("grid must be a list")
    if len(grid) == 0:
        return 1
    width = None
    for row in grid:
        if not isinstance(row, str):
            raise ValueError("row must be str")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("rows differ in length")
        for ch in row:
            if ch not in ".#":
                raise ValueError("bad character")
    height = len(grid)
    if width == 0:
        return 1
    cells = [[ch == "." for ch in row] for row in grid]
    if width > height:
        cells = [[cells[r][c] for r in range(height)] for c in range(width)]
        height, width = width, height
    if not any(any(row) for row in cells):
        return 1

    def free(r, c):
        return 0 <= r < height and 0 <= c < width and cells[r][c]

    states = {0: 1}
    for r in range(height):
        for c in range(width):
            new_states = {}
            is_free = cells[r][c]
            for mask, ways in states.items():
                if not is_free or (mask & 1):
                    if not is_free and (mask & 1):
                        continue
                    nm = mask >> 1
                    new_states[nm] = new_states.get(nm, 0) + ways
                    continue
                candidates = []
                right = free(r, c + 1) and not (mask >> 1) & 1
                down = free(r + 1, c) and not (mask >> width) & 1
                downright = free(r + 1, c + 1) and not (mask >> (width + 1)) & 1
                downleft = free(r + 1, c - 1) and not (mask >> (width - 1)) & 1
                if right:
                    candidates.append(1 << 1)
                if down:
                    candidates.append(1 << width)
                if right and down:
                    candidates.append((1 << 1) | (1 << width))
                if right and downright:
                    candidates.append((1 << 1) | (1 << (width + 1)))
                if down and downright:
                    candidates.append((1 << width) | (1 << (width + 1)))
                if down and downleft:
                    candidates.append((1 << width) | (1 << (width - 1)))
                for add in candidates:
                    nm = (mask | 1 | add) >> 1
                    new_states[nm] = new_states.get(nm, 0) + ways
            states = new_states
            if not states:
                return 0
    return states.get(0, 0)
```
