"""C3 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。

Connection Scan Algorithm を、乗った便の本数ごとの層（exactly k 本）に分けて 1 回だけ走査する。
depart < arrive なので、出発時刻順に並べれば、便 c に乗り継げる便は必ず c より前に処理されている。
"""

INF = float("inf")


def earliest_arrival(n: int, connections: list[tuple[int, int, int, int]], source: int, target: int,
                     start: int, change: int, max_transfers: int) -> int:
    if source == target:
        return start
    layers = max_transfers + 1
    # best[k][v]: ちょうど k 本の便で v に着ける最も早い時刻（k = 1..layers）
    best = [None] + [[INF] * n for _ in range(layers)]
    ordered = sorted(connections, key=lambda item: item[2])
    answer = INF
    for u, v, depart, arrive in ordered:
        if depart < start or arrive >= answer:
            continue
        if u == source:
            # 最初の便: 乗り換え時間は要らない
            if arrive < best[1][v]:
                best[1][v] = arrive
                if v == target:
                    answer = arrive
        limit = depart - change
        for k in range(2, layers + 1):
            if best[k - 1][u] <= limit and arrive < best[k][v]:
                best[k][v] = arrive
                if v == target:
                    answer = arrive
    return -1 if answer == INF else answer
