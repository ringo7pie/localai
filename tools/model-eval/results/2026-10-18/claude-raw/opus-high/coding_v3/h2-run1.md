```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    end_diag = m - n
    infinity = n + m + 10

    def slide_back(start_i: int, diag: int) -> int:
        i = start_i
        j = i + diag
        while i > 0 and j > 0 and a[i - 1] == b[j - 1]:
            i -= 1
            j -= 1
        return i

    # frontier[d][idx]: diagonal k = end_diag - d + idx (only even idx used).
    # value = smallest i on diagonal k with dist((i, i+k) -> (n, m)) <= d.
    # Along a diagonal, the distance to the end is non-increasing in i,
    # so dist(i, i+k) <= d  <=>  i >= frontier[d][idx].
    frontier: list[list[int]] = []
    first = slide_back(n, end_diag)
    frontier.append([first])
    total = None
    if end_diag == 0 and first == 0:
        total = 0
    dist = 0
    while total is None:
        dist += 1
        prev = frontier[dist - 1]
        prev_len = len(prev)
        row = [infinity] * (2 * dist + 1)
        for idx in range(0, 2 * dist + 1, 2):
            diag = end_diag - dist + idx
            cand = infinity
            # predecessor via "-": (x-1, x-1+diag) -> (x, x+diag-1) on diag-1
            p_idx = idx - 2
            if 0 <= p_idx < prev_len:
                x_val = prev[p_idx]
                if x_val < infinity and x_val >= 1:
                    cand = x_val - 1
            # predecessor via "+": (x, x+diag) -> (x, x+diag+1) on diag+1
            p_idx = idx
            if 0 <= p_idx < prev_len:
                x_val = prev[p_idx]
                if x_val < infinity and x_val + diag + 1 >= 1:
                    if x_val < cand:
                        cand = x_val
            if cand >= infinity:
                continue
            reached = slide_back(cand, diag)
            row[idx] = reached
            if diag == 0 and reached == 0:
                total = dist
        frontier.append(row)

    def dist_at_most(i: int, j: int, limit: int) -> bool:
        if limit < 0:
            return False
        diag = j - i
        idx = diag - end_diag + limit
        row = frontier[limit]
        if idx < 0 or idx >= len(row):
            return False
        return row[idx] <= i

    result: list[tuple] = []
    i = 0
    j = 0
    remaining = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
            continue
        if i < n and dist_at_most(i + 1, j, remaining - 1):
            result.append(("-", i))
            i += 1
        else:
            result.append(("+", j))
            j += 1
        remaining -= 1
    return result
```
