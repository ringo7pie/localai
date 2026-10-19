```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    ra = a[::-1]
    rb = b[::-1]

    # 逆向きの Myers 法。rows[d][(k + d) // 2] = 対角線 k で d 回の編集で届く最も遠い x
    rows: list[list[int]] = []
    total = -1
    d = 0
    while total < 0:
        row = [0] * (d + 1)
        prev = rows[d - 1] if d > 0 else None
        for idx in range(d + 1):
            k = -d + 2 * idx
            if d == 0:
                x = 0
            else:
                # prev の添字: 対角線 k' は (k' + d - 1) // 2
                if k == -d:
                    x = prev[(k + 1 + d - 1) // 2]
                elif k == d:
                    x = prev[(k - 1 + d - 1) // 2] + 1
                else:
                    up = prev[(k + 1 + d - 1) // 2]
                    left = prev[(k - 1 + d - 1) // 2]
                    if left < up:
                        x = up
                    else:
                        x = left + 1
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            row[idx] = x
            if x >= n and y >= m:
                total = d
        rows.append(row)
        d += 1

    def reachable(i: int, j: int, limit: int) -> bool:
        # (i, j) から末尾まで limit 回以下の編集で行けるか
        if limit < 0:
            return False
        x = n - i
        y = m - j
        k = x - y
        dd = limit if (limit - k) % 2 == 0 else limit - 1
        if dd < 0 or dd < abs(k):
            return False
        return rows[dd][(k + dd) // 2] >= x

    script: list[tuple] = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            script.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and reachable(i + 1, j, remaining - 1):
            script.append(("-", i))
            i += 1
            remaining -= 1
        else:
            script.append(("+", j))
            j += 1
            remaining -= 1
    return script
```
