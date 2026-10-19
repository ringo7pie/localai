```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    rev_a = a[::-1]
    rev_b = b[::-1]
    off = m + 1
    # far[k + off]: on diagonal k (x - y) of the reversed problem, the largest x
    # whose distance from the reversed start is <= current d (-1 if none).
    far = [-1] * (n + m + 3)
    delta = n - m

    x = 0
    while x < n and x < m and rev_a[x] == rev_b[x]:
        x += 1
    far[off] = x
    rows = [(0, [x])]
    total = 0 if (delta == 0 and x == n) else -1
    d = 0
    while total < 0:
        d += 1
        lo = -d
        if lo < -m:
            lo += ((-m - lo + 1) // 2) * 2
        hi = d
        if hi > n:
            hi -= ((hi - n + 1) // 2) * 2
        for k in range(lo, hi + 1, 2):
            idx = k + off
            best = far[idx]
            src = far[idx - 1]
            if src >= 0:
                if src < n:
                    cand = src + 1
                elif n >= 1:
                    cand = n
                else:
                    cand = -1
                if cand > best:
                    best = cand
            src = far[idx + 1]
            if src >= 0:
                if src - k <= m:
                    cand = src
                elif m >= 1:
                    cand = m + k
                else:
                    cand = -1
                if cand > best:
                    best = cand
            if best < 0:
                continue
            x = best
            y = x - k
            while x < n and y < m and rev_a[x] == rev_b[y]:
                x += 1
                y += 1
            far[idx] = x
        rows.append((lo, far[lo + off: hi + off + 1: 2]))
        if (delta - d) % 2 == 0 and -d <= delta <= d and far[delta + off] == n:
            total = d

    def reachable(limit: int, diag: int, xr: int) -> bool:
        if (diag - limit) % 2:
            limit -= 1
        if limit < 0:
            return False
        row_lo, vals = rows[limit]
        pos = diag - row_lo
        if pos < 0:
            return False
        pos //= 2
        if pos >= len(vals):
            return False
        return vals[pos] >= xr

    result = []
    i = 0
    j = 0
    remain = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and (
            j == m
            or reachable(remain - 1, (n - i - 1) - (m - j), n - i - 1)
        ):
            result.append(("-", i))
            i += 1
            remain -= 1
        else:
            result.append(("+", j))
            j += 1
            remain -= 1
    return result
```
