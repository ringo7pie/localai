"""H2 のオラクル（O(NM) の表。参照解とは別の作り）。

後ろからの距離の表 D[i][j]（a[i:] と b[j:] の、消す・足すだけの編集の数）を作り、先頭から "=" "-" "+" の順で
最短を保てる操作を選ぶ。もう 1 つは、すべての最短スクリプトを列挙して辞書順の最小を取る（とても小さい入力だけ）。
"""

from functools import lru_cache

ORDER = {"=": 0, "-": 1, "+": 2}


def ses_table(a, b):
    n, m = len(a), len(b)
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n:
                dist[i][j] = m - j
            elif j == m:
                dist[i][j] = n - i
            elif a[i] == b[j]:
                dist[i][j] = min(dist[i + 1][j + 1], 1 + min(dist[i + 1][j], dist[i][j + 1]))
            else:
                dist[i][j] = 1 + min(dist[i + 1][j], dist[i][j + 1])
    out, i, j = [], 0, 0
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j] and dist[i + 1][j + 1] == dist[i][j]:
            out.append(("=", i, j))
            i, j = i + 1, j + 1
        elif i < n and dist[i + 1][j] + 1 == dist[i][j]:
            out.append(("-", i))
            i += 1
        else:
            out.append(("+", j))
            j += 1
    return out


def ses_enumerate(a, b):
    n, m = len(a), len(b)

    @lru_cache(maxsize=None)
    def best(i, j):
        """(編集の数, 記号の並び) の最小（編集の数 → 辞書順）。"""
        if i == n and j == m:
            return (0, ())
        options = []
        if i < n and j < m and a[i] == b[j]:
            cost, rest = best(i + 1, j + 1)
            options.append((cost, (0,) + rest))
        if i < n:
            cost, rest = best(i + 1, j)
            options.append((cost + 1, (1,) + rest))
        if j < m:
            cost, rest = best(i, j + 1)
            options.append((cost + 1, (2,) + rest))
        return min(options)

    _cost, symbols = best(0, 0)
    out, i, j = [], 0, 0
    for sym in symbols:
        if sym == 0:
            out.append(("=", i, j))
            i, j = i + 1, j + 1
        elif sym == 1:
            out.append(("-", i))
            i += 1
        else:
            out.append(("+", j))
            j += 1
    return out
