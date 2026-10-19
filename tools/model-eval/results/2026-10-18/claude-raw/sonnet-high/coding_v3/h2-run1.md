```python
def _edit_distance(a, b):
    n = len(a)
    m = len(b)
    limit = n + m
    if limit == 0:
        return 0
    offset = limit + 1
    furthest = [0] * (2 * limit + 3)
    for d in range(limit + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and furthest[offset + k - 1] < furthest[offset + k + 1]):
                x = furthest[offset + k + 1]
            else:
                x = furthest[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            furthest[offset + k] = x
            if x >= n and y >= m:
                return d
    return limit


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    distance = _edit_distance(a, b)

    # 対角線 k = i - j の範囲。最短の道は、この範囲の外に出ない。
    diff = n - m
    extra = (distance - abs(diff)) // 2 + 1
    low = min(0, diff) - extra
    high = max(0, diff) + extra
    width = high - low + 1
    inf = 10 ** 9

    # rows[i][pos] = (i, j) から終わりまでの最小の編集数。pos = (i - j) - low + 1。
    rows = [None] * (n + 1)
    next_row = [inf] * (width + 2)
    for i in range(n, -1, -1):
        current = [inf] * (width + 2)
        j_min = max(0, i - high)
        j_max = min(m, i - low)
        a_item = a[i] if i < n else None
        for j in range(j_max, j_min - 1, -1):
            pos = i - j - low + 1
            if i == n and j == m:
                current[pos] = 0
            elif i < n and j < m and a_item == b[j]:
                current[pos] = next_row[pos]
            else:
                best = inf
                if i < n:
                    candidate = next_row[pos + 1] + 1
                    if candidate < best:
                        best = candidate
                if j < m:
                    candidate = current[pos - 1] + 1
                    if candidate < best:
                        best = candidate
                current[pos] = best
        rows[i] = current
        next_row = current

    script = []
    i = 0
    j = 0
    while i < n or j < m:
        pos = i - j - low + 1
        remaining = rows[i][pos]
        if i < n and j < m and a[i] == b[j]:
            script.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and rows[i + 1][pos + 1] + 1 == remaining:
            script.append(("-", i))
            i += 1
        else:
            script.append(("+", j))
            j += 1
    return script
```
