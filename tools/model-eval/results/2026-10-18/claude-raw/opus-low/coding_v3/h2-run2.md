```python
def _myers_distance(a, b):
    n, m = len(a), len(b)
    v = {1: 0}
    for d in range(n + m + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[k - 1] < v[k + 1]):
                x = v[k + 1]
            else:
                x = v[k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                return d
    return n + m


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    total = _myers_distance(a, b)
    delta = n - m
    slack = (total - abs(delta)) // 2
    lo = min(0, delta) - slack
    hi = max(0, delta) + slack
    width = hi - lo + 1
    inf = n + m + 1
    rows = [None] * (n + 1)
    nxt = None
    for i in range(n, -1, -1):
        row = [inf] * width
        for idx in range(width):
            j = i - (lo + idx)
            if j < 0 or j > m:
                continue
            if i == n:
                row[idx] = m - j
                continue
            if j == m:
                row[idx] = n - i
                continue
            best = inf
            if idx + 1 < width:
                best = nxt[idx + 1] + 1
            if idx > 0:
                cand = row[idx - 1] + 1
                if cand < best:
                    best = cand
            if a[i] == b[j]:
                cand = nxt[idx]
                if cand < best:
                    best = cand
            row[idx] = best
        rows[i] = row
        nxt = row

    def dist(i, j):
        idx = i - j - lo
        if idx < 0 or idx >= width or i > n or j > m:
            return inf
        return rows[i][idx]

    result = []
    i = j = 0
    while i < n or j < m:
        cur = dist(i, j)
        if i < n and j < m and a[i] == b[j] and dist(i + 1, j + 1) == cur:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and dist(i + 1, j) == cur - 1:
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
