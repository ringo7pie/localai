```python
def shortest_edit_script(a: list[str], b: list[str]) -> list[tuple]:
    n, m = len(a), len(b)
    ra = a[::-1]
    rb = b[::-1]
    offset = n + m + 1
    vec = [0] * (2 * offset + 2)
    trace = []
    total = 0
    d = 0
    while True:
        done = False
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and vec[offset + k - 1] < vec[offset + k + 1]):
                x = vec[offset + k + 1]
            else:
                x = vec[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and ra[x] == rb[y]:
                x += 1
                y += 1
            vec[offset + k] = x
            if x >= n and y >= m:
                done = True
        trace.append(vec[offset - d:offset + d + 1])
        if done:
            total = d
            break
        d += 1

    def reach(i, j, dist):
        if dist < 0:
            return False
        p = n - i
        q = m - j
        k = p - q
        if abs(k) > dist or (dist - k) % 2:
            return False
        return trace[dist][k + dist] >= p

    result = []
    i = j = 0
    cost = total
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            result.append(("=", i, j))
            i += 1
            j += 1
        elif i < n and reach(i + 1, j, cost - 1):
            result.append(("-", i))
            i += 1
            cost -= 1
        else:
            result.append(("+", j))
            j += 1
            cost -= 1
    return result
```
