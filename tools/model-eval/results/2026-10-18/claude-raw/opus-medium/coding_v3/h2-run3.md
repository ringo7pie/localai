```python
def _edit_distance(a: list[str], b: list[str]) -> int:
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return n + m
    max_d = n + m
    offset = max_d + 1
    reach = [-1] * (2 * max_d + 3)
    for d in range(max_d + 1):
        for k in range(-d, d + 1, 2):
            if k < -m or k > n:
                continue
            if d == 0:
                best = 0
            else:
                best = -1
                if k != d:
                    prev = reach[k + 1 + offset]
                    if prev >= 0 and prev - k <= m:
                        best = prev
                if k != -d:
                    prev = reach[k - 1 + offset]
                    if prev >= 0:
                        cand = prev + 1
                        if cand <= n and cand > best:
                            best = cand
            if best < 0:
                continue
            x = best
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            reach[k + offset] = x
            if x >= n and y >= m:
                return d
    return max_d


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    total = _edit_distance(a, b)
    ins_count = (total - (n - m)) // 2
    del_count = (total + (n - m)) // 2
    klo = -ins_count
    khi = del_count
    width = khi - klo + 1
    inf = 1 << 60

    rows: list[list[int]] = [None] * (n + 1)  # type: ignore
    for i in range(n, -1, -1):
        row = [inf] * width
        nxt = rows[i + 1] if i < n else None
        # j = i - k, need 0 <= j <= m  ->  i - m <= k <= i
        start = max(0, i - m - klo)
        stop = min(width - 1, i - klo)
        for kidx in range(start, stop + 1):
            j = i - (klo + kidx)
            if i == n and j == m:
                row[kidx] = 0
                continue
            if i < n and j < m and a[i] == b[j]:
                row[kidx] = nxt[kidx]
                continue
            val = inf
            if i < n and kidx + 1 < width:
                cand = nxt[kidx + 1] + 1
                if cand < val:
                    val = cand
            if j < m and kidx > 0:
                cand = row[kidx - 1] + 1
                if cand < val:
                    val = cand
            row[kidx] = val
        rows[i] = row

    result: list[tuple] = []
    i = j = 0
    while i < n or j < m:
        kidx = (i - j) - klo
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
            continue
        cur = rows[i][kidx]
        if i < n and kidx + 1 < width and rows[i + 1][kidx + 1] + 1 == cur:
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
