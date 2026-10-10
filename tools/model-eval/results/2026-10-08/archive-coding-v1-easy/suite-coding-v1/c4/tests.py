"""C4 LRUCache の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。"""

import collections
import random

FORBIDDEN_CALLS = ()


class _Reference:
    """答え合わせ用の LRU（OrderedDict）。"""

    def __init__(self, capacity):
        self.capacity = capacity
        self.items = collections.OrderedDict()

    def get(self, key):
        if key not in self.items:
            return -1
        self.items.move_to_end(key)
        return self.items[key]

    def put(self, key, value):
        self.items[key] = value
        self.items.move_to_end(key)
        if len(self.items) > self.capacity:
            self.items.popitem(last=False)


def case_basic_sequence(sol, t):
    cache = sol.LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    t.eq(cache.get(1), 1)
    cache.put(3, 3)
    t.eq(cache.get(2), -1)
    cache.put(4, 4)
    t.eq(cache.get(1), -1)
    t.eq(cache.get(3), 3)
    t.eq(cache.get(4), 4)


def case_capacity_one(sol, t):
    cache = sol.LRUCache(1)
    cache.put(1, 1)
    cache.put(2, 2)
    t.eq(cache.get(1), -1)
    t.eq(cache.get(2), 2)


def case_update_no_evict(sol, t):
    cache = sol.LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    cache.put(1, 10)
    t.eq(len(cache), 2)
    t.eq(cache.get(2), 2)
    t.eq(cache.get(1), 10)


def case_update_makes_recent(sol, t):
    cache = sol.LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    cache.put(1, 10)
    cache.put(3, 3)
    t.eq(cache.get(2), -1)
    t.eq(cache.get(1), 10)
    t.eq(cache.get(3), 3)


def case_get_makes_recent(sol, t):
    cache = sol.LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    t.eq(cache.get("a"), 1)
    cache.put("c", 3)
    t.eq(cache.get("b"), -1)
    t.eq(cache.get("a"), 1)


def case_missing_get_keeps_order(sol, t):
    cache = sol.LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    t.eq(cache.get(9), -1)
    cache.put(3, 3)
    t.eq(cache.get(1), -1)
    t.eq(cache.get(2), 2)


def case_bad_capacity(sol, t):
    t.raises(ValueError, sol.LRUCache, 0)
    t.raises(ValueError, sol.LRUCache, -3)


def case_len_tracks(sol, t):
    cache = sol.LRUCache(3)
    t.eq(len(cache), 0)
    cache.put("a", 1)
    t.eq(len(cache), 1)
    for key in ("b", "c", "d"):
        cache.put(key, 0)
    t.eq(len(cache), 3)


def case_put_returns_none(sol, t):
    cache = sol.LRUCache(2)
    t.eq(cache.put(1, 1), None)


def case_hashable_keys(sol, t):
    cache = sol.LRUCache(3)
    cache.put(("x", 1), "tuple-key")
    cache.put("y", None)
    t.eq(cache.get(("x", 1)), "tuple-key")
    t.eq(cache.get("y"), None)
    t.eq(cache.get("missing"), -1)


def case_random_many_ops(sol, t):
    # 20 万回の操作を参照実装と突き合わせる（O(n) の実装は harness の 1 ケース 3 秒で落ちることがある）
    rng = random.Random(4242)
    cache = sol.LRUCache(2000)
    reference = _Reference(2000)
    for step in range(200000):
        key = rng.randint(0, 5000)
        if rng.random() < 0.5:
            cache.put(key, step)
            reference.put(key, step)
        else:
            got, want = cache.get(key), reference.get(key)
            if got != want:
                t.eq((step, key, got), (step, key, want))
    t.eq(len(cache), len(reference.items))


CASES = [
    case_basic_sequence, case_capacity_one, case_update_no_evict, case_update_makes_recent,
    case_get_makes_recent, case_missing_get_keeps_order, case_bad_capacity, case_len_tracks,
    case_put_returns_none, case_hashable_keys, case_random_many_ops,
]
