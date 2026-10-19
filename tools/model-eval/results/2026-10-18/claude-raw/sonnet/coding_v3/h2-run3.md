```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    # 末尾から先頭へ向かう Myers 法。layers[d][(k + d) // 2] は、
    # 逆向きの列で対角線 k (= x - y) 上に d 回の編集で届く最も遠い x。
    # 逆向きの点 (x, y) は、元の列では a[n - x:] と b[m - y:] が残っている状態に当たる。
    ra = a[::-1]
    rb = b[::-1]
    target = n - m

    x = 0
    while x < n and x < m and ra[x] == rb[x]:
        x += 1
    layers = [[x]]
    distance = 0
    if not (target == 0 and x >= n):
        d = 0
        while True:
            d += 1
            prev = layers[d - 1]
            cur = []
            for k in range(-d, d + 1, 2):
                if k == -d:
                    x = prev[(k + d) // 2]
                elif k == d:
                    x = prev[(k + d - 2) // 2] + 1
                else:
                    x_right = prev[(k + d - 2) // 2] + 1
                    x_down = prev[(k + d) // 2]
                    x = x_right if x_right > x_down else x_down
                y = x - k
                while x < n and y < m and ra[x] == rb[y]:
                    x += 1
                    y += 1
                cur.append(x)
            layers.append(cur)
            if -d <= target <= d and (target + d) % 2 == 0:
                if cur[(target + d) // 2] >= n:
                    distance = d
                    break

    # 先頭から貪欲に選ぶ。残せるなら必ず残す（残しても最短のまま）。
    # 消すのは、消した後の残りの編集数が 1 減るときだけ。そうでなければ足す。
    operations: list[tuple] = []
    i = 0
    j = 0
    remaining = distance
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            operations.append(("=", i, j))
            i += 1
            j += 1
            continue
        can_delete = False
        if i < n:
            if j == m:
                can_delete = True
            else:
                next_x = n - i - 1
                diagonal = next_x - (m - j)
                if remaining >= 1 and abs(diagonal) <= remaining - 1:
                    layer = layers[remaining - 1]
                    if layer[(diagonal + remaining - 1) // 2] >= next_x:
                        can_delete = True
        if can_delete:
            operations.append(("-", i))
            i += 1
        else:
            operations.append(("+", j))
            j += 1
        remaining -= 1
    return operations
```
