"""H2 shortest_edit_script の参照解。

1. 後ろから Myers の O((N+M)D) を回し、コスト d ごとに各対角線で最も遠くまで届く点 V_d[k] を残す
   （後ろ向きの座標: x = 残りの a の数、y = 残りの b の数、k = x - y）。
2. 「点 (i, j) から終わりまでの編集の数が r 以下か」は、対角線の上で距離が単調に増えることから、
   r と偶奇をそろえた r' について x <= V_r'[k] で判定できる。
3. 先頭から、最短を保てる操作のうち "=" "-" "+" の順で最初のものを選ぶ。
"""


def _backward_frontiers(a, b):
    n, m = len(a), len(b)
    ra, rb = a[::-1], b[::-1]
    frontiers = []
    prev = {}
    for d in range(n + m + 1):
        snapshot = {}
        for k in range(max(-d, -m), min(d, n) + 1):
            if (k - d) % 2:
                continue
            if d == 0:
                x = 0
            else:
                best = -1
                down = prev.get(k + 1)          # (x, y) から (x, y + 1)
                if down is not None and down - k <= m:
                    best = down
                right = prev.get(k - 1)         # (x, y) から (x + 1, y)
                if right is not None and right + 1 <= n and right + 1 > best:
                    best = right + 1
                if best < 0:
                    continue
                x = best
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            snapshot[k] = x
        frontiers.append(snapshot)
        if snapshot.get(n - m, -1) >= n:
            return frontiers, d
        prev = snapshot
    raise AssertionError("unreachable")


def shortest_edit_script(a, b):
    a, b = list(a), list(b)
    n, m = len(a), len(b)
    frontiers, total = _backward_frontiers(a, b)

    def fits(i, j, budget):
        x, y = n - i, m - j
        k = x - y
        if budget < 0:
            return False
        if (budget - k) % 2:
            budget -= 1
        if budget < abs(k):
            return False
        return x <= frontiers[budget].get(k, -1)

    script = []
    i = j = spent = 0
    while i < n or j < m:
        left = total - spent
        if i < n and j < m and a[i] == b[j] and fits(i + 1, j + 1, left):
            script.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and fits(i + 1, j, left - 1):
            script.append(("-", i))
            i += 1
            spent += 1
        else:
            script.append(("+", j))
            j += 1
            spent += 1
    return script
