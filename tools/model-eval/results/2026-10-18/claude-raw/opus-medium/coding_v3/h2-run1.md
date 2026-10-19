```python
def _myers_distance(a: list[str], b: list[str]) -> int:
    n = len(a)
    m = len(b)
    max_d = n + m
    offset = max_d + 1
    furthest = [0] * (2 * max_d + 3)
    for d in range(max_d + 1):
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
    return max_d


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    total = _myers_distance(a, b)
    delta = m - n
    slack = (total - abs(delta)) // 2 + 1
    lo = min(0, delta) - slack
    hi = max(0, delta) + slack
    INF = 1 << 40

    rows: list[list[int]] = [[] for _ in range(n + 2)]
    starts = [0] * (n + 2)

    for i in range(n, -1, -1):
        s = max(0, i + lo)
        e = min(m, i + hi)
        starts[i] = s
        if s > e:
            rows[i] = []
            continue
        row = [INF] * (e - s + 1)
        nrow = rows[i + 1]
        ns = starts[i + 1]
        nl = len(nrow)
        right = INF
        ai = a[i] if i < n else None
        for j in range(e, s - 1, -1):
            if i == n and j == m:
                v = 0
            else:
                v = right + 1 if j < m else INF
                if i < n:
                    idx = j - ns
                    if 0 <= idx < nl:
                        t = nrow[idx] + 1
                        if t < v:
                            v = t
                    if j < m and ai == b[j]:
                        idx2 = idx + 1
                        if 0 <= idx2 < nl:
                            t = nrow[idx2]
                            if t < v:
                                v = t
            row[j - s] = v
            right = v
        rows[i] = row

    def get(i: int, j: int) -> int:
        if i > n or j > m:
            return INF
        row = rows[i]
        idx = j - starts[i]
        if 0 <= idx < len(row):
            return row[idx]
        return INF

    result: list[tuple] = []
    i = 0
    j = 0
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
