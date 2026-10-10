"""C6 topo_sort の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。"""

import copy
import heapq
import random

FORBIDDEN_CALLS = ()


def _reference(graph):
    nodes = set(graph)
    for targets in graph.values():
        nodes.update(targets)
    indegree = {node: 0 for node in nodes}
    edges = {node: set() for node in nodes}
    for source, targets in graph.items():
        for target in set(targets):
            edges[source].add(target)
            indegree[target] += 1
    ready = [node for node in nodes if indegree[node] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for target in edges[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    return order


def case_empty(sol, t):
    t.eq(list(sol.topo_sort({})), [])


def case_single(sol, t):
    t.eq(list(sol.topo_sort({"a": []})), ["a"])


def case_node_only_in_lists(sol, t):
    t.eq(list(sol.topo_sort({"a": ["b"]})), ["a", "b"])


def case_ties_sorted(sol, t):
    t.eq(list(sol.topo_sort({"c": [], "b": [], "a": []})), ["a", "b", "c"])


def case_smallest_available(sol, t):
    # a は c と d の後。最初に置けるのは b・c・d で、a は最後になる
    t.eq(list(sol.topo_sort({"d": ["a"], "c": ["a"], "b": []})), ["b", "c", "d", "a"])


def case_case_sensitive_order(sol, t):
    # Python の < では大文字が小文字より小さい
    t.eq(list(sol.topo_sort({"b": [], "B": [], "a": []})), ["B", "a", "b"])


def case_self_loop(sol, t):
    t.raises(ValueError, sol.topo_sort, {"a": ["a"]})


def case_deep_cycle(sol, t):
    t.raises(ValueError, sol.topo_sort, {"a": ["b"], "b": ["c"], "c": ["d"], "d": ["b"]})


def case_duplicate_edges(sol, t):
    t.eq(list(sol.topo_sort({"a": ["b", "b"], "b": []})), ["a", "b"])


def case_input_unchanged(sol, t):
    graph = {"b": ["a", "c"], "a": [], "c": ["a"]}
    snapshot = copy.deepcopy(graph)
    t.eq(list(sol.topo_sort(graph)), ["b", "c", "a"])
    t.eq(graph, snapshot)


def case_long_chain(sol, t):
    # 名前の辞書順と逆向きの 5,000 個の鎖（再帰の DFS は深さで落ちる）
    names = [f"n{index:04d}" for index in range(5000)]
    graph = {names[index]: [names[index - 1]] for index in range(1, 5000)}
    t.eq(list(sol.topo_sort(graph)), list(reversed(names)))


def case_random_dag(sol, t):
    rng = random.Random(77)
    names = [f"v{rng.randint(0, 10 ** 6):07d}_{index}" for index in range(3000)]
    order = names[:]
    rng.shuffle(order)
    graph = {name: [] for name in names if rng.random() < 0.9}
    for _ in range(9000):
        first, second = sorted(rng.sample(range(3000), 2))
        graph.setdefault(order[first], []).append(order[second])
    t.eq(list(sol.topo_sort(graph)), _reference(graph))


CASES = [
    case_empty, case_single, case_node_only_in_lists, case_ties_sorted, case_smallest_available,
    case_case_sensitive_order, case_self_loop, case_deep_cycle, case_duplicate_edges, case_input_unchanged,
    case_long_chain, case_random_dag,
]
