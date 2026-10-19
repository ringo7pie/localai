```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    len_a = len(a)
    len_b = len(b)
    rev_a = a[::-1]
    rev_b = b[::-1]

    # 逆向きの問題（後ろから読む）で、対角線 k = x - y ごとに
    # 「編集 d 以下で行ける最も先の x」を持つ。
    # frontiers[d][k + d] が d 回以内で届く最大の x（届かなければ -1）。
    # 対角線上で距離は単調に増えるので、x がこの値以下の点はすべて d 以内で届く。
    start_x = 0
    while start_x < len_a and start_x < len_b and rev_a[start_x] == rev_b[start_x]:
        start_x += 1
    frontiers = [[start_x]]
    target_diag = len_a - len_b

    depth = 0
    while not (abs(target_diag) <= depth and frontiers[depth][target_diag + depth] >= len_a):
        depth += 1
        prev_depth = depth - 1
        prev = frontiers[prev_depth]
        cur = [-1] + prev + [-1]
        for diag in range(-depth, depth + 1, 2):
            if diag < -len_b or diag > len_a:
                continue
            best = cur[diag + depth]
            cand = -1
            # a の要素を消す手: 対角線 diag - 1 から
            src = diag - 1
            if src >= -prev_depth:
                reach = prev[src + prev_depth]
                if reach >= 0:
                    src_x = reach if reach < len_a else len_a - 1
                    if src_x >= 0 and src_x >= src:
                        cand = src_x + 1
            # b の要素を足す手: 対角線 diag + 1 から
            src = diag + 1
            if src <= prev_depth:
                reach = prev[src + prev_depth]
                if reach >= 0:
                    src_x = reach if reach < len_b + diag else len_b + diag
                    if src_x >= 0 and src_x >= src and src_x > cand:
                        cand = src_x
            if cand > best:
                pos_x = cand
                pos_y = pos_x - diag
                while pos_x < len_a and pos_y < len_b and rev_a[pos_x] == rev_b[pos_y]:
                    pos_x += 1
                    pos_y += 1
                cur[diag + depth] = pos_x
        frontiers.append(cur)

    total = depth

    def within(next_i: int, next_j: int, budget: int) -> bool:
        # a[next_i:] と b[next_j:] の編集距離が budget 以下か
        if budget < 0:
            return False
        x_rev = len_a - next_i
        y_rev = len_b - next_j
        diag = x_rev - y_rev
        if diag > budget or -diag > budget:
            return False
        return frontiers[budget][diag + budget] >= x_rev

    script: list[tuple] = []
    i = 0
    j = 0
    remaining = total
    while i < len_a or j < len_b:
        if i < len_a and j < len_b and a[i] == b[j]:
            script.append(("=", i, j))
            i += 1
            j += 1
        elif i < len_a and within(i + 1, j, remaining - 1):
            script.append(("-", i))
            i += 1
            remaining -= 1
        else:
            script.append(("+", j))
            j += 1
            remaining -= 1
    return script
```
