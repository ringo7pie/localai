```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    INF = 10**9
    delta = n - m
    lo = min(0, delta)
    hi = max(0, delta)

    def attempt(w):
        # 対角 c = i - j が [lo - w, hi + w] の帯だけで、末尾からの距離を求める
        jlow = [max(0, i - hi - w) for i in range(n + 1)]
        jhigh = [min(m, i - lo + w) for i in range(n + 1)]
        rows = [None] * (n + 1)

        def get(i, j):
            if i > n or j > m:
                return INF
            if j < jlow[i] or j > jhigh[i]:
                return INF
            return rows[i][j - jlow[i]]

        for i in range(n, -1, -1):
            low = jlow[i]
            high = jhigh[i]
            if low > high:
                rows[i] = []
                continue
            row = [INF] * (high - low + 1)
            rows[i] = row
            nxt = rows[i + 1] if i < n else None
            if i < n:
                nlow = jlow[i + 1]
                nhigh = jhigh[i + 1]
            ai = a[i] if i < n else None
            for j in range(high, low - 1, -1):
                if i == n:
                    val = m - j
                elif j == m:
                    val = n - i
                else:
                    if ai == b[j]:
                        k = j + 1
                        val = nxt[k - nlow] if nlow <= k <= nhigh else INF
                    else:
                        down = nxt[j - nlow] if nlow <= j <= nhigh else INF
                        right = row[j + 1 - low] if j + 1 <= high else INF
                        val = 1 + (down if down < right else right)
                        if val > INF:
                            val = INF
                row[j - low] = val
        return get, get(0, 0)

    w = 8
    while True:
        get, total = attempt(w)
        full = (lo - w <= -n) and (hi + w >= m)
        if total < INF and (total < abs(delta) + 2 * (w + 1) or full):
            break
        if full:
            break
        w *= 2

    result = []
    i = 0
    j = 0
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and get(i + 1, j) + 1 == get(i, j):
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
    return result
```
