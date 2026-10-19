```python
def _edit_distance(a, b):
    n = len(a)
    m = len(b)
    offset = n + m + 1
    v = [0] * (2 * offset + 3)
    for d in range(n + m + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]
            else:
                x = v[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return d
    return n + m


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    total = _edit_distance(a, b)
    diff = n - m
    lo = max(-total, diff - total)
    hi = min(total, diff + total)
    INF = 1 << 30

    starts = [0] * (n + 1)
    rows = [None] * (n + 1)
    for i in range(n, -1, -1):
        j_lo = max(0, i - hi)
        j_hi = min(m, i - lo)
        starts[i] = j_lo
        if j_hi < j_lo:
            rows[i] = []
            continue
        row = [INF] * (j_hi - j_lo + 1)
        if i == n:
            for j in range(j_lo, j_hi + 1):
                row[j - j_lo] = m - j
        else:
            nxt = rows[i + 1]
            nstart = starts[i + 1]
            nlen = len(nxt)
            ai = a[i]
            for j in range(j_hi, j_lo - 1, -1):
                if j == m:
                    row[j - j_lo] = n - i
                    continue
                if ai == b[j]:
                    idx = j + 1 - nstart
                    row[j - j_lo] = nxt[idx] if 0 <= idx < nlen else INF
                else:
                    best = INF
                    idx = j - nstart
                    if 0 <= idx < nlen:
                        best = nxt[idx]
                    idx = j + 1 - j_lo
                    if idx < len(row) and row[idx] < best:
                        best = row[idx]
                    row[j - j_lo] = best + 1 if best < INF else INF
        rows[i] = row

    def get(i, j):
        if i > n or j > m:
            return INF
        row = rows[i]
        idx = j - starts[i]
        if 0 <= idx < len(row):
            return row[idx]
        return INF

    result = []
    i = 0
    j = 0
    while i < n or j < m:
        current = get(i, j)
        if i < n and j < m and a[i] == b[j] and get(i + 1, j + 1) == current:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and get(i + 1, j) + 1 == current:
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
