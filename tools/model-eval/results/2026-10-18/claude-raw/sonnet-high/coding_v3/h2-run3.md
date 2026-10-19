```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    ra = a[::-1]
    rb = b[::-1]
    NEG = -10**9

    # 末尾側から Myers 法を走らせる。
    # W[d][k + d] = 対角 k (= p - q) 上で、a[i:] と b[j:] の編集距離が d 以下になる
    # 点のうち最も遠い p (p = n - i, q = m - j)。
    # 対角に沿って編集距離は単調非減少なので、「p <= W[d][k + d]」と
    # 「その点の距離 <= d」は同値になる。
    W = []
    target = n - m
    d = 0
    while True:
        cur = [NEG] * (2 * d + 1)
        prev = W[d - 1] if d >= 1 else None
        prev2 = W[d - 2] if d >= 2 else None
        for k in range(-d, d + 1, 2):
            if d == 0:
                x = 0
            else:
                x = NEG
                if k - 1 >= -(d - 1):
                    v = prev[k - 1 + d - 1]
                    if v > NEG and v + 1 <= n and v + 1 > x:
                        x = v + 1
                if k + 1 <= d - 1:
                    v = prev[k + 1 + d - 1]
                    if v > NEG and v - k <= m and v > x:
                        x = v
                if d >= 2 and -(d - 2) <= k <= d - 2:
                    v = prev2[k + d - 2]
                    if v > x:
                        x = v
                if x == NEG:
                    continue
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            cur[k + d] = x
        W.append(cur)
        if -d <= target <= d and cur[target + d] == n:
            break
        d += 1
    remaining = d

    def feasible(i: int, j: int, budget: int) -> bool:
        if budget < 0:
            return False
        p = n - i
        q = m - j
        k = p - q
        if k < -budget or k > budget:
            return False
        return p <= W[budget][k + budget]

    result = []
    i = 0
    j = 0
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
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
