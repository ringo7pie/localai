"""C6 の参照解（tests/test_units.py で隠しテストを確かめる用）。Kahn 法を最小ヒープで回す。"""

import heapq


def topo_sort(graph: dict[str, list[str]]) -> list[str]:
    nodes = set(graph)
    for targets in graph.values():
        nodes.update(targets)
    edges = {node: set() for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, targets in graph.items():
        for target in set(targets):
            edges[source].add(target)
            indegree[target] += 1
    ready = [node for node in nodes if indegree[node] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for target in edges[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if len(order) != len(nodes):
        raise ValueError("graph has a cycle")
    return order
