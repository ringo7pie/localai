```python
def _reverse_myers_history(a: list[str], b: list[str]):
    """Run Myers' algorithm on the reversed sequences.

    Returns (dtot, hist) where hist[d][k + d] is the furthest x (in reversed
    coordinates, x = n - i) reachable on diagonal k = x - y with d edits,
    or -1 if no in-grid point on that diagonal is reachable with d edits.
    """
    n, m = len(a), len(b)
    ra = a[::-1]
    rb = b[::-1]
    max_d = n + m
    off = max_d + 1
    v = [-1] * (2 * max_d + 3)
    hist = []

    x = 0
    while x < n and x < m and ra[x] == rb[x]:
        x += 1
    v[off] = x
    hist.append([x])
    if x == n and x == m:
        return 0, hist

    d = 0
    while True:
        d += 1
        found = False
        for k in range(-d, d + 1, 2):
            best = -1
            src = v[off + k + 1]
            if src >= 0 and src - k <= m:
                best = src
            src = v[off + k - 1]
            if src >= 0 and src + 1 <= n and src + 1 > best:
                best = src + 1
            if best < 0:
                v[off + k] = -1
                continue
            x = best
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            v[off + k] = x
            if x == n and y == m:
                found = True
                break
        hist.append(v[off - d:off + d + 1])
        if found:
            return d, hist


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    dtot, hist = _reverse_myers_history(a, b)

    def within(i: int, j: int, dist: int) -> bool:
        # True if the edit distance from (i, j) to the end is <= dist.
        if dist < 0:
            return False
        xr = n - i
        yr = m - j
        k = xr - yr
        if k > dist or -k > dist:
            return False
        return hist[dist][k + dist] >= xr

    result = []
    i = 0
    j = 0
    cur = dtot
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and (j >= m or within(i + 1, j, cur - 1)):
            result.append(("-", i))
            i += 1
            cur -= 1
        else:
            result.append(("+", j))
            j += 1
            cur -= 1
    return result
```
