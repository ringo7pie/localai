```python
def _myers_snapshots(ra: list[int], rb: list[int]) -> tuple[int, list[list[int]]]:
    """Run Myers' O((N+M)D) algorithm on (ra, rb) and keep, for every round d,
    the furthest-reaching x on each diagonal k in [-d, d] (index k + d)."""
    n = len(ra)
    m = len(rb)
    max_d = n + m
    offset = max_d + 1
    frontier = [0] * (2 * max_d + 3)
    snapshots: list[list[int]] = []
    target = n - m
    for d in range(max_d + 1):
        found = False
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and frontier[offset + k - 1] < frontier[offset + k + 1]):
                x = frontier[offset + k + 1]
            else:
                x = frontier[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            frontier[offset + k] = x
            if k == target and x >= n:
                found = True
                break
        snapshots.append(frontier[offset - d: offset + d + 1])
        if found:
            return d, snapshots
    return max_d, snapshots


def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n = len(a)
    m = len(b)
    ids: dict[str, int] = {}
    a_ids = [ids.setdefault(item, len(ids)) for item in a]
    b_ids = [ids.setdefault(item, len(ids)) for item in b]

    # Distances to the end of the original sequences are distances from the
    # origin on the reversed sequences.
    total, snapshots = _myers_snapshots(a_ids[::-1], b_ids[::-1])

    def remaining_at_most(i: int, j: int, limit: int) -> bool:
        # True iff the edit distance between a[i:] and b[j:] is <= limit,
        # given that it has the same parity as limit (it is limit or limit + 2).
        if limit < 0:
            return False
        x = n - i
        y = m - j
        diagonal = x - y
        if diagonal < -limit or diagonal > limit:
            return False
        return snapshots[limit][diagonal + limit] >= x

    script: list[tuple] = []
    i = 0
    j = 0
    current = total
    while i < n or j < m:
        if i < n and j < m and a_ids[i] == b_ids[j]:
            script.append(("=", i, j))
            i += 1
            j += 1
        elif i == n:
            script.append(("+", j))
            j += 1
            current -= 1
        elif j == m:
            script.append(("-", i))
            i += 1
            current -= 1
        elif remaining_at_most(i + 1, j, current - 1):
            script.append(("-", i))
            i += 1
            current -= 1
        else:
            script.append(("+", j))
            j += 1
            current -= 1
    return script
```
