```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("alphabet must be a non-empty string")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet has duplicate characters")


class _Parser:
    def __init__(self, pattern, alphabet):
        if not isinstance(pattern, str):
            raise ValueError("pattern must be a string")
        self.p = pattern
        self.n = len(pattern)
        self.i = 0
        self.alpha = alphabet
        self.alphaset = frozenset(alphabet)

    def parse(self):
        node = self.parse_alt()
        if self.i != self.n:
            raise ValueError("unbalanced parenthesis")
        return node

    def parse_alt(self):
        branches = [self.parse_concat()]
        while self.i < self.n and self.p[self.i] == "|":
            self.i += 1
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_concat(self):
        items = []
        last_quant = False
        while self.i < self.n:
            ch = self.p[self.i]
            if ch in "|)":
                break
            if ch in "*+?":
                if not items or last_quant:
                    raise ValueError("nothing to repeat")
                kind = {"*": "star", "+": "plus", "?": "opt"}[ch]
                items[-1] = (kind, items[-1])
                last_quant = True
                self.i += 1
                continue
            items.append(self.parse_atom())
            last_quant = False
        if not items:
            return ("eps",)
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def _lit(self, char):
        if char in self.alphaset:
            return ("set", frozenset([char]))
        return ("set", frozenset())

    def parse_atom(self):
        ch = self.p[self.i]
        if ch == "(":
            self.i += 1
            node = self.parse_alt()
            if self.i >= self.n or self.p[self.i] != ")":
                raise ValueError("missing )")
            self.i += 1
            return node
        if ch == ".":
            self.i += 1
            return ("set", self.alphaset)
        if ch == "\\":
            if self.i + 1 >= self.n:
                raise ValueError("trailing backslash")
            char = self.p[self.i + 1]
            self.i += 2
            return self._lit(char)
        if ch == "[":
            return self.parse_class()
        self.i += 1
        return self._lit(ch)

    def _class_char(self, pos):
        if pos >= self.n:
            raise ValueError("unterminated class")
        if self.p[pos] == "\\":
            if pos + 1 >= self.n:
                raise ValueError("trailing backslash")
            return self.p[pos + 1], pos + 2
        return self.p[pos], pos + 1

    def parse_class(self):
        p, n = self.p, self.n
        pos = self.i + 1
        negate = False
        if pos < n and p[pos] == "^":
            negate = True
            pos += 1
        ranges = []
        while True:
            if pos >= n:
                raise ValueError("unterminated class")
            if p[pos] == "]":
                if not ranges:
                    raise ValueError("empty class")
                pos += 1
                break
            low, pos = self._class_char(pos)
            if pos < n and p[pos] == "-" and pos + 1 < n and p[pos + 1] != "]":
                high, pos = self._class_char(pos + 1)
                if ord(low) > ord(high):
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                ranges.append((low, low))
        self.i = pos
        matched = set()
        for char in self.alpha:
            for low, high in ranges:
                if low <= char <= high:
                    matched.add(char)
                    break
        if negate:
            matched = set(self.alpha) - matched
        return ("set", frozenset(matched))


def _build_nfa(ast):
    eps = []
    chars = []

    def new():
        eps.append([])
        chars.append(None)
        return len(eps) - 1

    def build(node):
        kind = node[0]
        if kind == "set":
            start = new()
            end = new()
            chars[start] = (node[1], end)
            return start, end
        if kind == "eps":
            start = new()
            end = new()
            eps[start].append(end)
            return start, end
        if kind == "cat":
            start, end = build(node[1][0])
            for sub in node[1][1:]:
                sub_start, sub_end = build(sub)
                eps[end].append(sub_start)
                end = sub_end
            return start, end
        if kind == "alt":
            start = new()
            end = new()
            for sub in node[1]:
                sub_start, sub_end = build(sub)
                eps[start].append(sub_start)
                eps[sub_end].append(end)
            return start, end
        inner_start, inner_end = build(node[1])
        start = new()
        end = new()
        eps[start].append(inner_start)
        eps[inner_end].append(end)
        if kind in ("star", "opt"):
            eps[start].append(end)
        if kind in ("star", "plus"):
            eps[inner_end].append(inner_start)
        return start, end

    start, end = build(ast)
    return eps, chars, start, end


class _DFA:
    def __init__(self, pattern, alphabet):
        ast = _Parser(pattern, alphabet).parse()
        eps, chars, nfa_start, nfa_end = _build_nfa(ast)
        count = len(eps)
        self.k = len(alphabet)
        self.end = nfa_end
        important = [chars[q] is not None or q == nfa_end for q in range(count)]
        closure_mask = [0] * count
        for q in range(count):
            seen = {q}
            stack = [q]
            mask = 0
            while stack:
                cur = stack.pop()
                if important[cur]:
                    mask |= 1 << cur
                for nxt in eps[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            closure_mask[q] = mask
        trans = [()] * count
        for q in range(count):
            if chars[q] is None:
                continue
            charset, target = chars[q]
            entries = []
            for idx, char in enumerate(alphabet):
                if char in charset:
                    entries.append((idx, closure_mask[target]))
            trans[q] = tuple(entries)
        self.trans = trans
        start_mask = closure_mask[nfa_start]
        self.ids = {start_mask: 0}
        self.masks = [start_mask]
        self.accept = [bool((start_mask >> nfa_end) & 1)]
        self.rows = [None]

    def _state(self, mask):
        sid = self.ids.get(mask)
        if sid is None:
            sid = len(self.masks)
            self.ids[mask] = sid
            self.masks.append(mask)
            self.accept.append(bool((mask >> self.end) & 1))
            self.rows.append(None)
        return sid

    def row(self, sid):
        row = self.rows[sid]
        if row is not None:
            return row
        acc = [0] * self.k
        mask = self.masks[sid]
        trans = self.trans
        while mask:
            low = mask & -mask
            q = low.bit_length() - 1
            mask ^= low
            for idx, tmask in trans[q]:
                acc[idx] |= tmask
        row = [self._state(m) for m in acc]
        self.rows[sid] = row
        return row

    def build_all(self):
        sid = 0
        while sid < len(self.masks):
            self.row(sid)
            sid += 1


def _minimal_count(rows, accept, k):
    n = len(rows)
    inv = [[[] for _ in range(n)] for _ in range(k)]
    for s in range(n):
        row = rows[s]
        for c in range(k):
            inv[c][row[c]].append(s)
    acc = [s for s in range(n) if accept[s]]
    rej = [s for s in range(n) if not accept[s]]
    blocks = []
    block_of = [0] * n
    for group in (acc, rej):
        if group:
            bid = len(blocks)
            blocks.append(set(group))
            for s in group:
                block_of[s] = bid
    if len(blocks) < 2:
        return len(blocks)
    first = 0 if len(blocks[0]) <= len(blocks[1]) else 1
    work = [first]
    in_work = {first}
    while work:
        splitter = work.pop()
        in_work.discard(splitter)
        members = list(blocks[splitter])
        for c in range(k):
            inv_c = inv[c]
            touched = {}
            for t in members:
                for s in inv_c[t]:
                    b = block_of[s]
                    lst = touched.get(b)
                    if lst is None:
                        touched[b] = [s]
                    else:
                        lst.append(s)
            for b, lst in touched.items():
                blk = blocks[b]
                if len(lst) == len(blk):
                    continue
                new_set = set(lst)
                blk.difference_update(new_set)
                nb = len(blocks)
                blocks.append(new_set)
                for s in lst:
                    block_of[s] = nb
                if b in in_work:
                    work.append(nb)
                    in_work.add(nb)
                elif len(new_set) <= len(blk):
                    work.append(nb)
                    in_work.add(nb)
                else:
                    work.append(b)
                    in_work.add(b)
    return len(blocks)


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    dfa = _DFA(pattern, alphabet)
    dfa.build_all()
    return _minimal_count(dfa.rows, dfa.accept, len(alphabet))


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    dfa1 = _DFA(p1, alphabet)
    dfa2 = _DFA(p2, alphabet)
    if dfa1.accept[0] != dfa2.accept[0]:
        return ""
    k = len(alphabet)
    start = (0, 0)
    parent = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        row1 = dfa1.row(node[0])
        row2 = dfa2.row(node[1])
        for c in range(k):
            nxt = (row1[c], row2[c])
            if nxt in parent:
                continue
            parent[nxt] = (node, c)
            if dfa1.accept[nxt[0]] != dfa2.accept[nxt[1]]:
                letters = []
                cur = nxt
                while parent[cur] is not None:
                    prev, idx = parent[cur]
                    letters.append(alphabet[idx])
                    cur = prev
                letters.reverse()
                return "".join(letters)
            queue.append(nxt)
    return None
```
