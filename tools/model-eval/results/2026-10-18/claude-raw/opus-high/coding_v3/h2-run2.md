```python
def _backward_frontiers(a, b):
    """Myers の貪欲法を逆順の列に適用する。
    hist[d][k + d] は、逆順の座標で対角線 k (= x - y) 上の、編集 d 回以下で届く最も遠い x。
    届かなければ -1。"""
    ra = a[::-1]
    rb = b[::-1]
    len_a = len(ra)
    len_b = len(rb)
    hist = []
    prev = None
    d = 0
    while True:
        cur = [-1] * (2 * d + 1)
        finished = False
        for k in range(-d, d + 1):
            if (d - k) % 2:
                if prev is not None and -(d - 1) <= k <= d - 1:
                    cur[k + d] = prev[k + d - 1]
                continue
            if d == 0:
                best = 0
            else:
                best = -1
                if -(d - 1) <= k <= d - 1:
                    best = prev[k + d - 1]
                if k + 1 <= d - 1:
                    px = prev[k + 1 + d - 1]
                    if px >= 0 and px - k <= len_b and px > best:
                        best = px
                if k - 1 >= -(d - 1):
                    px = prev[k - 1 + d - 1]
                    if px >= 0 and px + 1 <= len_a and px + 1 > best:
                        best = px + 1
            if best < 0:
                continue
            x = best
            y = x - k
            while x < len_a and y < len_b and ra[x] == rb[y]:
                x += 1
                y += 1
            cur[k + d] = x
            if x == len_a and y == len_b:
                finished = True
        hist.append(cur)
        if finished:
            return hist, d
        prev = cur
        d += 1


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    hist, total = _backward_frontiers(a, b)

    def reach(x, y, d):
        # 逆順の座標 (x, y) に、編集 d 回以下で届くか
        if d < 0:
            return False
        k = x - y
        if k > d or k < -d:
            return False
        if d >= len(hist):
            d = len(hist) - 1
            if k > d or k < -d:
                return False
        v = hist[d][k + d]
        return v >= 0 and x <= v

    result = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
            continue
        if i < n and (j == m or reach(n - i - 1, m - j, remaining - 1)):
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
        remaining -= 1
    return result
```
