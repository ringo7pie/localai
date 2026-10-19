```python
def _edit_distance(a, b):
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return n + m
    max_d = n + m
    offset = max_d + 1
    v = [0] * (2 * max_d + 3)
    for d in range(max_d + 1):
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
    return max_d


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    total = _edit_distance(a, b)
    delta = n - m
    slack = (total - abs(delta)) // 2
    klo = min(0, delta) - slack
    khi = max(0, delta) + slack
    width = khi - klo + 1
    INF = 10 ** 9
    dist = [[INF] * width for _ in range(n + 1)]

    for i in range(n, -1, -1):
        row = dist[i]
        next_row = dist[i + 1] if i < n else None
        j_high = min(m, i - klo)
        j_low = max(0, i - khi)
        for j in range(j_high, j_low - 1, -1):
            idx = i - j - klo
            if i == n and j == m:
                row[idx] = 0
                continue
            if i < n and j < m and a[i] == b[j]:
                row[idx] = next_row[idx]
                continue
            best = INF
            if i < n and idx + 1 < width:
                value = next_row[idx + 1] + 1
                if value < best:
                    best = value
            if j < m and idx >= 1:
                value = row[idx - 1] + 1
                if value < best:
                    best = value
            row[idx] = best

    result = []
    i = j = 0
    while i < n or j < m:
        idx = i - j - klo
        current = dist[i][idx]
        if i < n and j < m and a[i] == b[j] and dist[i + 1][idx] == current:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and idx + 1 < width and dist[i + 1][idx + 1] + 1 == current:
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
