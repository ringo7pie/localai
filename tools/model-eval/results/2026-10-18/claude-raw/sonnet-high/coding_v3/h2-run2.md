```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    ra = a[::-1]
    rb = b[::-1]

    # 末尾から先頭へ向かう Myers 法 (O(ND))。各 d の最遠到達点を保存する。
    # history[d][k + d] = 対角線 k (= x - y, 逆向きの座標) で d 回の編集で届く最大の x
    history = []
    previous = {0: 0}
    total = 0
    found = False
    d = 0
    while not found:
        current = [-1] * (2 * d + 1)
        layer = {}
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and previous.get(k - 1, -1) < previous.get(k + 1, -1)):
                x = previous.get(k + 1, 0)
            else:
                x = previous.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            layer[k] = x
            current[k + d] = x
            if x >= n and y >= m:
                found = True
        history.append(current)
        previous = layer
        if found:
            total = d
            break
        d += 1

    def within(i: int, j: int, limit: int) -> bool:
        # 位置 (i, j) から末尾までの最小編集数が limit 以下か
        if limit < 0:
            return False
        x = n - i
        y = m - j
        k = x - y
        if (limit - k) % 2 != 0:
            limit -= 1
            if limit < 0:
                return False
        if k > limit or -k > limit:
            return False
        return x <= history[limit][k + limit]

    result = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and remaining >= 1 and within(i + 1, j, remaining - 1):
            result.append(("-", i))
            i += 1
            remaining -= 1
        else:
            result.append(("+", j))
            j += 1
            remaining -= 1
    return result
```
