```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    INF = 1 << 30

    def band(limit):
        width = 2 * limit + 1
        rows = [None] * (n + 1)
        nxt = None
        for i in range(n, -1, -1):
            row = [INF] * width
            t_lo = max(0, limit - i)
            t_hi = min(width - 1, m - i + limit)
            for t in range(t_hi, t_lo - 1, -1):
                j = i - limit + t
                if i == n and j == m:
                    row[t] = 0
                    continue
                best = INF
                if i < n:
                    if j < m and a[i] == b[j]:
                        best = nxt[t]
                    if t >= 1:
                        val = nxt[t - 1] + 1
                        if val < best:
                            best = val
                if j < m and t + 1 < width:
                    val = row[t + 1] + 1
                    if val < best:
                        best = val
                row[t] = best
            rows[i] = row
            nxt = row
        return rows

    limit = max(1, abs(n - m))
    while True:
        rows = band(limit)
        if rows[0][limit] <= limit:
            break
        limit *= 2

    width = 2 * limit + 1

    def get(i, j):
        if i > n or j > m:
            return INF
        t = j - i + limit
        if t < 0 or t >= width:
            return INF
        return rows[i][t]

    result = []
    i = j = 0
    remaining = get(0, 0)
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j] and get(i + 1, j + 1) == remaining:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and get(i + 1, j) == remaining - 1:
            result.append(("-", i))
            i += 1
            remaining -= 1
        else:
            result.append(("+", j))
            j += 1
            remaining -= 1
    return result
```
