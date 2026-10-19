```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    ra = a[::-1]
    rb = b[::-1]
    off = m + 1
    size = n + m + 3
    values = [-1] * size
    snaps = []
    target = n - m
    d = 0
    # Myers on reversed sequences: snaps[d][off+k] = furthest x on diagonal k
    # (reversed coordinates) reachable with <= d edits.
    while True:
        if -d >= -m:
            k = -d
        else:
            k = -m if (d - m) % 2 == 0 else -m + 1
        hi = min(d, n)
        while k <= hi:
            if d == 0:
                x = 0
            else:
                x = -1
                up = values[off + k + 1]
                if up >= 0 and up - k <= m:
                    x = up
                left = values[off + k - 1]
                if left >= 0 and left + 1 <= n and left + 1 > x:
                    x = left + 1
                if x < 0:
                    k += 2
                    continue
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            if x > values[off + k]:
                values[off + k] = x
            k += 2
        snaps.append(values[:])
        if values[off + target] >= n:
            break
        d += 1

    remaining = d
    result = []
    i = j = 0
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
            continue
        if i < n:
            budget = remaining - 1
            x = n - i - 1
            y = m - j
            k = x - y
            if budget >= 0 and -budget <= k <= budget and snaps[budget][off + k] >= x:
                result.append(("-", i))
                i += 1
                remaining -= 1
                continue
        result.append(("+", j))
        j += 1
        remaining -= 1
    return result
```
