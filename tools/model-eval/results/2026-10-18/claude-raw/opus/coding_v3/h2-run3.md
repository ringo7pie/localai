```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    result: list[tuple] = []

    # 先頭の共通部分は、辞書順でも最短でも必ず "=" になる
    prefix = 0
    limit = min(len(a), len(b))
    while prefix < limit and a[prefix] == b[prefix]:
        result.append(("=", prefix, prefix))
        prefix += 1

    # 比較を速くするため、行を整数に置き換える
    try:
        ids: dict = {}
        seq_a = [ids.setdefault(item, len(ids)) for item in a[prefix:]]
        seq_b = [ids.setdefault(item, len(ids)) for item in b[prefix:]]
    except TypeError:
        seq_a = list(a[prefix:])
        seq_b = list(b[prefix:])

    n_len = len(seq_a)
    m_len = len(seq_b)

    # 逆順の列で Myers の前進を行う。
    # fronts[d][kr + m_len] は、逆順の格子の対角線 kr (= x - y) 上で
    # 原点からの編集数が d 以下になる点の x の最大値（無ければ -1）。
    # 原点からの距離は対角線に沿って単調に増えないので、x 以下の点はすべて d 以下で届く。
    # 逆順の点 (x, y) は、元の位置 (n_len - x, m_len - y) から終点までの距離に対応する。
    rev_a = seq_a[::-1]
    rev_b = seq_b[::-1]
    offset = m_len
    size = n_len + m_len + 1

    front = [-1] * size
    x_pos = 0
    while x_pos < n_len and x_pos < m_len and rev_a[x_pos] == rev_b[x_pos]:
        x_pos += 1
    front[offset] = x_pos
    fronts: list[list[int]] = [front]

    end_index = n_len - m_len + offset
    dist_total = 0
    while front[end_index] < n_len:
        dist_total += 1
        prev = front
        front = prev[:]
        low = max(-dist_total, -m_len)
        high = min(dist_total, n_len)
        for diag in range(low, high + 1):
            idx = diag + offset
            best = prev[idx]
            # 対角線 diag-1 から a を 1 つ消して移る
            if diag - 1 >= -m_len and n_len >= 1:
                prev_x = prev[idx - 1]
                if prev_x >= 0:
                    cand = prev_x + 1 if prev_x < n_len else n_len
                    if cand > best:
                        best = cand
            # 対角線 diag+1 から b を 1 つ足して移る
            if diag + 1 <= n_len and m_len >= 1:
                prev_x = prev[idx + 1]
                if prev_x >= 0:
                    cap = m_len + diag
                    cand = prev_x if prev_x < cap else cap
                    if cand > best:
                        best = cand
            if best < 0:
                continue
            x_pos = best
            y_pos = x_pos - diag
            while x_pos < n_len and y_pos < m_len and rev_a[x_pos] == rev_b[y_pos]:
                x_pos += 1
                y_pos += 1
            front[idx] = x_pos
        fronts.append(front)

    # 前から貪欲に、最短を保てる最小の記号を選ぶ
    remaining = dist_total
    pos_a = 0
    pos_b = 0
    while pos_a < n_len or pos_b < m_len:
        if pos_a < n_len and pos_b < m_len and seq_a[pos_a] == seq_b[pos_b]:
            result.append(("=", pos_a + prefix, pos_b + prefix))
            pos_a += 1
            pos_b += 1
            continue
        if pos_a < n_len:
            # (pos_a + 1, pos_b) から終点までの距離が remaining - 1 以下か
            rev_x = n_len - pos_a - 1
            idx = rev_x - (m_len - pos_b) + offset
            if fronts[remaining - 1][idx] >= rev_x:
                result.append(("-", pos_a + prefix))
                pos_a += 1
                remaining -= 1
                continue
        result.append(("+", pos_b + prefix))
        pos_b += 1
        remaining -= 1

    return result
```
