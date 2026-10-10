"""C3 earliest_arrival の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

大きなケースの期待値は、層ごとの DP（便の順序に依存しない別実装）と小さな例の全経路探索で照合して固定した。
"""

import random

FORBIDDEN_CALLS = ()


def _random_instance(seed: int, n: int, count: int, planted_legs: int):
    """乱数で便を作る。source 0 から target n-1 へ、planted_legs 本の便をつないだ経路を 1 つ必ず入れる。"""

    rng = random.Random(seed)
    connections = []
    for _ in range(count):
        u = rng.randrange(n)
        v = rng.randrange(n)
        depart = rng.randrange(0, 1_000_000)
        connections.append((u, v, depart, depart + rng.randrange(1, 2000)))
    stops = [0] + [rng.randrange(1, n - 1) for _ in range(planted_legs - 1)] + [n - 1]
    time = rng.randrange(0, 1000)
    for index in range(planted_legs):
        depart = time + rng.randrange(60, 600)
        arrive = depart + rng.randrange(1, 600)
        connections.append((stops[index], stops[index + 1], depart, arrive))
        time = arrive
    rng.shuffle(connections)
    return connections


def case_source_is_target(sol, t):
    t.eq(sol.earliest_arrival(1, [], 0, 0, 5, 0, 0), 5)
    t.eq(sol.earliest_arrival(2, [(0, 0, 6, 7), (0, 1, 1, 2)], 0, 0, 5, 0, 0), 5)
    t.eq(sol.earliest_arrival(3, [(0, 1, 1, 2)], 2, 2, 100, 3, 1), 100)


def case_no_connections(sol, t):
    t.eq(sol.earliest_arrival(2, [], 0, 1, 0, 0, 5), -1)
    t.eq(sol.earliest_arrival(3, [(0, 1, 0, 1)], 0, 2, 0, 0, 5), -1)


def case_direct_departure_boundary(sol, t):
    t.eq(sol.earliest_arrival(2, [(0, 1, 5, 9)], 0, 1, 5, 0, 0), 9)
    t.eq(sol.earliest_arrival(2, [(0, 1, 5, 9)], 0, 1, 4, 0, 0), 9)
    t.eq(sol.earliest_arrival(2, [(0, 1, 5, 9)], 0, 1, 6, 0, 3), -1)


def case_direct_minimizes_arrival_not_departure(sol, t):
    t.eq(sol.earliest_arrival(2, [(0, 1, 0, 100), (0, 1, 10, 20), (0, 1, 5, 50)], 0, 1, 0, 0, 0), 20)
    t.eq(sol.earliest_arrival(2, [(0, 1, 0, 100), (0, 1, 10, 20), (0, 1, 5, 50)], 0, 1, 6, 0, 0), 20)
    t.eq(sol.earliest_arrival(2, [(0, 1, 0, 100), (0, 1, 10, 20), (0, 1, 5, 50)], 0, 1, 11, 0, 0), -1)


def case_tight_transfer_with_zero_change(sol, t):
    t.eq(sol.earliest_arrival(3, [(0, 1, 10, 20), (1, 2, 20, 30)], 0, 2, 0, 0, 1), 30)
    t.eq(sol.earliest_arrival(3, [(0, 1, 10, 20), (1, 2, 20, 30)], 0, 2, 0, 1, 1), -1)
    t.eq(sol.earliest_arrival(3, [(0, 1, 10, 20), (1, 2, 19, 30)], 0, 2, 0, 0, 1), -1)


def case_change_time_selects_later_connection(sol, t):
    connections = [(0, 1, 10, 20), (1, 2, 25, 30), (1, 2, 22, 40)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 5, 1), 30)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 6, 1), -1)
    connections = [(0, 1, 10, 20), (1, 2, 25, 30), (1, 2, 22, 26)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 2, 1), 26)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 3, 1), 30)


def case_transfer_limit_zero_means_direct_only(sol, t):
    connections = [(0, 1, 10, 20), (1, 2, 25, 30), (0, 2, 0, 100)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 0), 100)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 1), 30)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 10), 30)


def case_transfer_limit_makes_it_impossible(sol, t):
    chain = [(0, 1, 0, 1), (1, 2, 2, 3), (2, 3, 4, 5)]
    t.eq(sol.earliest_arrival(4, chain, 0, 3, 0, 0, 1), -1)
    t.eq(sol.earliest_arrival(4, chain, 0, 3, 0, 0, 2), 5)
    t.eq(sol.earliest_arrival(4, chain, 0, 3, 0, 1, 2), 5)
    t.eq(sol.earliest_arrival(4, chain, 0, 3, 0, 2, 2), -1)


def case_earliest_departure_is_a_trap(sol, t):
    connections = [(0, 1, 0, 10), (1, 3, 11, 100), (0, 2, 5, 6), (2, 3, 7, 8)]
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 1), 8)
    connections = [(0, 1, 0, 50), (1, 2, 50, 60), (0, 1, 20, 30), (1, 2, 31, 40)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 1, 1), 40)


def case_waiting_at_intermediate_station(sol, t):
    t.eq(sol.earliest_arrival(3, [(0, 1, 0, 1), (1, 2, 50, 51)], 0, 2, 0, 0, 1), 51)
    t.eq(sol.earliest_arrival(3, [(0, 1, 0, 1), (1, 2, 50, 51), (1, 2, 30, 60)], 0, 2, 0, 0, 1), 51)


def case_equal_departure_times_cannot_chain(sol, t):
    t.eq(sol.earliest_arrival(3, [(0, 1, 5, 6), (1, 2, 5, 7)], 0, 2, 0, 0, 1), -1)
    t.eq(sol.earliest_arrival(3, [(0, 1, 5, 6), (1, 2, 6, 7)], 0, 2, 0, 0, 1), 7)
    t.eq(sol.earliest_arrival(3, [(1, 2, 6, 7), (0, 1, 5, 6)], 0, 2, 0, 0, 1), 7)


def case_duplicates_and_self_loops(sol, t):
    connections = [(0, 1, 0, 5), (0, 1, 0, 5), (1, 1, 5, 6), (1, 2, 6, 7), (1, 2, 5, 9)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 2), 7)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 1), 7)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 1, 1), 7)
    # 自己ループ (1, 1, 5, 6) に乗っても乗り換え時間は省けない
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 2, 2), -1)


def case_more_transfers_arrive_earlier(sol, t):
    connections = [(0, 1, 0, 2), (1, 2, 2, 5), (2, 4, 6, 9), (0, 3, 1, 5), (3, 4, 6, 12), (0, 4, 2, 20)]
    t.eq(sol.earliest_arrival(5, connections, 0, 4, 0, 0, 2), 9)
    t.eq(sol.earliest_arrival(5, connections, 0, 4, 0, 0, 1), 12)
    t.eq(sol.earliest_arrival(5, connections, 0, 4, 0, 0, 0), 20)
    t.eq(sol.earliest_arrival(5, connections, 0, 4, 0, 1, 2), 12)
    t.eq(sol.earliest_arrival(5, connections, 0, 4, 0, 2, 2), 20)


def case_earliest_arrival_at_a_station_may_use_too_many_transfers(sol, t):
    # 駅 1 に最も早く着く経路（0→2→1、乗り換え 1 回）の先で便に乗ると上限を超える。遅い直通 0→1 を使う必要がある。
    # 駅ごとに最早到着だけを持つ解法は -1 を返してしまう
    connections = [(0, 2, 0, 1), (2, 1, 2, 3), (0, 1, 0, 10), (1, 3, 20, 25)]
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 1), 25)
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 2), 25)
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 0), -1)
    connections = [(0, 2, 0, 1), (2, 1, 2, 3), (0, 1, 0, 10), (1, 3, 5, 8), (1, 3, 20, 25)]
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 2), 8)
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 1), 25)


def case_fast_and_slow_stages(sol, t):
    # 各区間に「速いが 2 本」と「遅いが 1 本」の行き方がある。上限に合わせて最後の区間だけ速い方を選ぶ
    stages = 6
    connections = []
    for index in range(stages):
        base = 100 * index
        connections.append((index, index + 1, base, base + 10))
        connections.append((index, 100 + index, base, base + 1))
        connections.append((100 + index, index + 1, base + 2, base + 3))
    final = 100 * (stages - 1)
    t.eq(sol.earliest_arrival(200, connections, 0, stages, 0, 1, stages), final + 3)
    t.eq(sol.earliest_arrival(200, connections, 0, stages, 0, 1, stages - 1), final + 10)
    t.eq(sol.earliest_arrival(200, connections, 0, stages, 0, 1, stages - 2), -1)
    t.eq(sol.earliest_arrival(200, connections, 0, stages, 0, 1, 2 * stages - 1), final + 3)


def case_connections_before_start_are_useless(sol, t):
    connections = [(0, 1, 0, 1), (1, 2, 2, 3), (0, 1, 10, 11), (1, 2, 12, 13)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 5, 0, 1), 13)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 0, 0, 1), 3)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, 1, 0, 1), 13)


def case_large_time_values(sol, t):
    big = 10 ** 9
    connections = [(0, 1, big - 10, big - 5), (1, 2, big - 5, big), (0, 2, big - 100, big - 1)]
    t.eq(sol.earliest_arrival(3, connections, 0, 2, big - 100, 0, 1), big - 1)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, big - 99, 0, 1), big)
    t.eq(sol.earliest_arrival(3, connections, 0, 2, big - 99, 1, 1), -1)


def case_disconnected_graph(sol, t):
    connections = [(0, 1, 0, 1), (1, 0, 2, 3), (2, 3, 0, 1), (3, 2, 2, 3)]
    t.eq(sol.earliest_arrival(4, connections, 0, 3, 0, 0, 10), -1)
    t.eq(sol.earliest_arrival(4, connections, 2, 3, 0, 0, 0), 1)


def case_chain_at_the_transfer_limit(sol, t):
    chain = [(index, index + 1, 10 * index, 10 * index + 5) for index in range(11)]
    t.eq(sol.earliest_arrival(12, chain, 0, 11, 0, 5, 10), 105)
    t.eq(sol.earliest_arrival(12, chain, 0, 11, 0, 5, 9), -1)
    t.eq(sol.earliest_arrival(12, chain, 0, 11, 0, 6, 10), -1)
    t.eq(sol.earliest_arrival(12, chain, 0, 6, 0, 5, 5), 55)


def case_many_stations_few_connections(sol, t):
    n = 100_000
    connections = [(0, n - 1, 7, 9), (0, 5, 1, 2), (5, n - 1, 3, 4)]
    t.eq(sol.earliest_arrival(n, connections, 0, n - 1, 0, 0, 1), 4)
    t.eq(sol.earliest_arrival(n, connections, 0, n - 1, 0, 0, 0), 9)
    t.eq(sol.earliest_arrival(n, connections, 0, n - 1, 2, 0, 5), 9)


def case_random_small_instances(sol, t):
    # 小さな乱数の例（期待値は全経路探索で固定）
    for seed, n, count, legs, change, max_transfers, expected in RANDOM_SMALL:
        connections = _random_instance(seed, n, count, legs)
        t.eq(sol.earliest_arrival(n, connections, 0, n - 1, 0, change, max_transfers), expected)


def case_perf_wide_random_graph(sol, t):
    connections = _random_instance(31, 20_000, 100_000, 5)
    t.eq(sol.earliest_arrival(20_000, connections, 0, 19_999, 0, 30, 4), PERF_EXPECTED["wide"])


def case_perf_max_connections_few_transfers(sol, t):
    connections = _random_instance(32, 50_000, 200_000, 2)
    t.eq(sol.earliest_arrival(50_000, connections, 0, 49_999, 0, 0, 1), PERF_EXPECTED["max_connections"])


def case_perf_many_transfer_layers(sol, t):
    connections = _random_instance(33, 5_000, 60_000, 11)
    t.eq(sol.earliest_arrival(5_000, connections, 0, 4_999, 0, 10, 10), PERF_EXPECTED["layers"])


def case_perf_stages_with_many_decoys(sol, t):
    # case_fast_and_slow_stages を大きくしたもの。各区間に 8,000 通りの「速いが 2 本」の行き方がある
    stages, decoys = 10, 8_000
    connections = []
    for index in range(stages):
        base = 100 * index
        connections.append((index, index + 1, base, base + 10))
        for decoy in range(decoys):
            middle = stages + 1 + index * decoys + decoy
            connections.append((index, middle, base, base + 1))
            connections.append((middle, index + 1, base + 2, base + 3))
    n = stages + 1 + stages * decoys
    final = 100 * (stages - 1)
    t.eq(sol.earliest_arrival(n, connections, 0, stages, 0, 1, stages), final + 3)
    t.eq(sol.earliest_arrival(n, connections, 0, stages, 0, 1, stages - 1), final + 10)


# (seed, n, count, legs, change, max_transfers, expected)
RANDOM_SMALL = [
    (1, 6, 12, 2, 0, 3, 1701),
    (2, 6, 12, 2, 5, 1, 2251),
    (3, 7, 20, 3, 0, 2, 2453),
    (4, 7, 20, 3, 100, 2, 1752),
    (5, 8, 30, 3, 0, 1, 50446),
    (6, 8, 30, 3, 0, 0, -1),
    (7, 9, 40, 4, 50, 3, 3377),
    (8, 9, 40, 4, 50, 10, 2439),
]
PERF_EXPECTED = {"wide": 3044, "max_connections": 2250, "layers": 7764}

CASES = [
    case_source_is_target, case_no_connections, case_direct_departure_boundary,
    case_direct_minimizes_arrival_not_departure, case_tight_transfer_with_zero_change,
    case_change_time_selects_later_connection, case_transfer_limit_zero_means_direct_only,
    case_transfer_limit_makes_it_impossible, case_earliest_departure_is_a_trap, case_waiting_at_intermediate_station,
    case_equal_departure_times_cannot_chain, case_duplicates_and_self_loops, case_more_transfers_arrive_earlier,
    case_earliest_arrival_at_a_station_may_use_too_many_transfers, case_fast_and_slow_stages,
    case_connections_before_start_are_useless, case_large_time_values, case_disconnected_graph,
    case_chain_at_the_transfer_limit, case_many_stations_few_connections, case_random_small_instances,
    case_perf_wide_random_graph, case_perf_max_connections_few_transfers, case_perf_many_transfer_layers,
    case_perf_stages_with_many_decoys,
]
