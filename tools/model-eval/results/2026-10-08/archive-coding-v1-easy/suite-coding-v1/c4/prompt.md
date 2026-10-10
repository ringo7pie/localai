## 問題 C4: LRU キャッシュ

クラス `LRUCache` を書いてください。

- `LRUCache(capacity: int)`: 最大 `capacity` 個の「キーと値の組」を保持するキャッシュを作る。`capacity` が 1 未満なら `ValueError` を送出する。
- `get(key)`: `key` があればその値を返し、その組を「最も最近使った」ものにする。無ければ `-1` を返す（このとき順番は変えない）。
- `put(key, value)`: `key` の値を `value` にし、その組を「最も最近使った」ものにする。戻り値は `None`。新しい `key` を入れて組の数が `capacity` を超えるときは、「最も長く使っていない」組を 1 つ取り除く。既にある `key` の更新では何も取り除かない。
- `len(cache)` で、いま保持している組の数を返す。
- `key` はハッシュ可能な任意の値。`get` と `put` は平均 O(1) で動くこと（数十万回呼ばれる）。

例:
- `cache = LRUCache(2)` のあと `cache.put(1, 1)`、`cache.put(2, 2)`、`cache.get(1)` → `1`、`cache.put(3, 3)`（キー 2 が取り除かれる）、`cache.get(2)` → `-1`
- `cache = LRUCache(1)` のあと `cache.put("a", 10)`、`cache.put("a", 20)`、`cache.get("a")` → `20`、`len(cache)` → `1`
