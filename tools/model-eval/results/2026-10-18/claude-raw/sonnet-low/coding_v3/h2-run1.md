```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    ra = a[::-1]
    rb = b[::-1]
    history = []
    prev = {1: 0}
    total = 0
    d = 0
    while True:
        cur = {}
        found = False
        for k in range(-d, d + 1, 2):
            best = -1
            if (k + 1) in prev:
                x = prev[k + 1]
                y = x - k
                if 0 <= y <= m and x <= n:
                    best = x
            if (k - 1) in prev:
                x = prev[k - 1] + 1
                y = x - k
                if x <= n and 0 <= y <= m and x > best:
                    best = x
            if best < 0:
                continue
            x = best
            while x < n and x - k < m and ra[x] == rb[x - k]:
                x += 1
            cur[k] = x
            if k == n - m and x == n:
                found = True
        history.append(cur)
        if found:
            total = d
            break
        prev = cur
        d += 1

    def feasible(i: int, j: int, remaining: int) -> bool:
        if remaining < 0:
            return False
        x = n - i
        y = m - j
        k = x - y
        dd = remaining if (remaining - k) % 2 == 0 else remaining - 1
        if dd < 0 or dd > total:
            return False
        return history[dd].get(k, -1) >= x

    result = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j] and feasible(i + 1, j + 1, remaining):
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and feasible(i + 1, j, remaining - 1):
            result.append(("-", i))
            i += 1
            remaining -= 1
        else:
            result.append(("+", j))
            j += 1
            remaining -= 1
    return result
```
