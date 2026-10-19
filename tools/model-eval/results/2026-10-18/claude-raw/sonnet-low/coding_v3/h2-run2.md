```python
def _edit_distance(a, b):
    n, m = len(a), len(b)
    if n + m == 0:
        return 0
    offset = n + m + 1
    v = [0] * (2 * offset + 2)
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
    n, m = len(a), len(b)
    dist = _edit_distance(a, b)
    k0 = n - m
    slack = (dist - abs(k0)) // 2
    klo = min(0, k0) - slack
    khi = max(0, k0) + slack
    width = khi - klo + 1
    INF = 1 << 30
    rows = [None] * (n + 2)
    rows[n + 1] = [INF] * width
    for i in range(n, -1, -1):
        row = [INF] * width
        nxt = rows[i + 1]
        for k in range(klo, khi + 1):
            j = i - k
            if j < 0 or j > m:
                continue
            idx = k - klo
            if i == n and j == m:
                row[idx] = 0
                continue
            best = INF
            if i < n and j < m and a[i] == b[j]:
                best = nxt[idx]
            if i < n and idx + 1 < width:
                cand = nxt[idx + 1] + 1
                if cand < best:
                    best = cand
            if j < m and idx - 1 >= 0:
                cand = row[idx - 1] + 1
                if cand < best:
                    best = cand
            row[idx] = best
        rows[i] = row

    def get(i, j):
        if i > n or j > m:
            return INF
        k = i - j
        if k < klo or k > khi:
            return INF
        return rows[i][k - klo]

    result = []
    i = j = 0
    while i < n or j < m:
        cur = get(i, j)
        if i < n and j < m and a[i] == b[j] and get(i + 1, j + 1) == cur:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and get(i + 1, j) + 1 == cur:
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
