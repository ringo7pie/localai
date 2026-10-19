```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    # 末尾から先頭へ向かう向きで Myers の O(ND) を走らせる。
    # history[d][(k + d) // 2] は、d 回の編集で対角線 k = x - y 上に届く最も先の x。
    # 反転した列の点 (x, y) は、元の列の位置 (i, j) = (n - x, m - y) に対応し、
    # 「a[i:] を b[j:] に変える最小の編集数」を調べるのに使う。
    ra = a[::-1]
    rb = b[::-1]
    target = n - m

    x = 0
    while x < n and x < m and ra[x] == rb[x]:
        x += 1
    history = [[x]]
    total = 0
    if not (target == 0 and x >= n):
        d = 0
        while True:
            d += 1
            prev = history[-1]
            row = [0] * (d + 1)
            for idx in range(d + 1):
                k = 2 * idx - d
                if idx == 0:
                    x = prev[0]
                elif idx == d:
                    x = prev[d - 1] + 1
                else:
                    down = prev[idx]
                    right = prev[idx - 1] + 1
                    x = down if down > right else right
                y = x - k
                while x < n and y < m and ra[x] == rb[y]:
                    x += 1
                    y += 1
                row[idx] = x
            history.append(row)
            if abs(target) <= d and (target + d) % 2 == 0 and row[(target + d) // 2] >= n:
                total = d
                break

    def within(x_pos: int, y_pos: int, limit: int) -> bool:
        # a[n - x_pos:] を b[m - y_pos:] に変える編集数が limit 以下か。
        diagonal = x_pos - y_pos
        steps = abs(diagonal)
        while steps <= limit:
            if history[steps][(diagonal + steps) // 2] >= x_pos:
                return True
            steps += 2
        return False

    operations: list[tuple] = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            operations.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and (j == m or within(n - i - 1, m - j, remaining - 1)):
            operations.append(("-", i))
            i += 1
            remaining -= 1
        else:
            operations.append(("+", j))
            j += 1
            remaining -= 1
    return operations
```
