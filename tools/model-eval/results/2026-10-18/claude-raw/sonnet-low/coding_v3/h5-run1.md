```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("bad alphabet")
    if len(alphabet) > 8:
        raise ValueError("bad alphabet")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.p = pattern
        self.n = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.full = frozenset(range(len(alphabet)))
        self.eps = []
        self.trans = []

    def new_state(self):
        self.eps.append([])
        self.trans.append([])
        return len(self.eps) - 1

    def parse(self):
        frag = self.parse_alt()
        if self.pos < self.n:
            raise ValueError("unmatched )")
        return frag

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.pos < self.n and self.p[self.pos] == "|":
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        start = self.new_state()
        end = self.new_state()
        for b_start, b_end in branches:
            self.eps[start].append(b_start)
            self.eps[b_end].append(end)
        return (start, end)

    def parse_seq(self):
        start = self.new_state()
        cur = start
        while self.pos < self.n and self.p[self.pos] not in "|)":
            f_start, f_end = self.parse_quantified()
            self.eps[cur].append(f_start)
            cur = f_end
        return (start, cur)

    def parse_quantified(self):
        f_start, f_end = self.parse_atom()
        if self.pos < self.n and self.p[self.pos] in "*+?":
            q = self.p[self.pos]
            self.pos += 1
            s = self.new_state()
            e = self.new_state()
            self.eps[s].append(f_start)
            self.eps[f_end].append(e)
            if q in "*?":
                self.eps[s].append(e)
            if q in "*+":
                self.eps[f_end].append(f_start)
            return (s, e)
        return (f_start, f_end)

    def charset_frag(self, chars):
        s = self.new_state()
        e = self.new_state()
        if chars:
            self.trans[s].append((frozenset(chars), e))
        return (s, e)

    def parse_atom(self):
        ch = self.p[self.pos]
        if ch in "*+?":
            raise ValueError("nothing to repeat")
        if ch == "(":
            self.pos += 1
            frag = self.parse_alt()
            if self.pos >= self.n or self.p[self.pos] != ")":
                raise ValueError("unmatched (")
            self.pos += 1
            return frag
        if ch == "[":
            self.pos += 1
            return self.charset_frag(self.parse_class())
        if ch == ".":
            self.pos += 1
            return self.charset_frag(self.full)
        if ch == "\\":
            if self.pos + 1 >= self.n:
                raise ValueError("trailing backslash")
            lit = self.p[self.pos + 1]
            self.pos += 2
        else:
            lit = ch
            self.pos += 1
        if lit in self.index:
            return self.charset_frag({self.index[lit]})
        return self.charset_frag(set())

    def read_class_char(self):
        if self.pos >= self.n:
            raise ValueError("unclosed class")
        ch = self.p[self.pos]
        if ch == "\\":
            if self.pos + 1 >= self.n:
                raise ValueError("unclosed class")
            self.pos += 2
            return self.p[self.pos - 1]
        self.pos += 1
        return ch

    def parse_class(self):
        negate = False
        if self.pos < self.n and self.p[self.pos] == "^":
            negate = True
            self.pos += 1
        chosen = set()
        items = 0
        while True:
            if self.pos >= self.n:
                raise ValueError("unclosed class")
            if self.p[self.pos] == "]":
                self.pos += 1
                break
            low = self.read_class_char()
            if (self.pos + 1 < self.n and self.p[self.pos] == "-"
                    and self.p[self.pos + 1] != "]"):
                self.pos += 1
                high = self.read_class_char()
                if low > high:
                    raise ValueError("bad range")
                for ch, idx in self.index.items():
                    if low <= ch <= high:
                        chosen.add(idx)
            else:
                if low in self.index:
                    chosen.add(self.index[low])
            items += 1
        if items == 0:
            raise ValueError("empty class")
        if negate:
            return set(self.full) - chosen
        return chosen


def _build_dfa(pattern, alphabet):
    parser = _Parser(pattern, alphabet)
    start, end = parser.parse()
    eps = parser.eps
    trans = parser.trans
    size = len(eps)
    k = len(alphabet)

    closure_memo = {}

    def closure_of(state):
        cached = closure_memo.get(state)
        if cached is not None:
            return cached
        seen = {state}
        stack = [state]
        while stack:
            cur = stack.pop()
            for nxt in eps[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        result = frozenset(seen)
        closure_memo[state] = result
        return result

    moves = [[[] for _ in range(k)] for _ in range(size)]
    for state in range(size):
        for chars, target in trans[state]:
            for idx in chars:
                moves[state][idx].append(target)

    start_set = closure_of(start)
    ids = {start_set: 0}
    sets = [start_set]
    table = []
    pos = 0
    while pos < len(sets):
        current = sets[pos]
        row = []
        for idx in range(k):
            targets = set()
            for state in current:
                for target in moves[state][idx]:
                    targets |= closure_of(target)
            frozen = frozenset(targets)
            found = ids.get(frozen)
            if found is None:
                found = len(sets)
                ids[frozen] = found
                sets.append(frozen)
            row.append(found)
        table.append(row)
        pos += 1
    accepting = [end in current for current in sets]
    return table, accepting


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    table, accepting = _build_dfa(pattern, alphabet)
    count = len(table)
    cls = [1 if accepting[i] else 0 for i in range(count)]
    num = len(set(cls))
    while True:
        sigs = {}
        new_cls = [0] * count
        for state in range(count):
            sig = (cls[state],) + tuple(cls[t] for t in table[state])
            got = sigs.get(sig)
            if got is None:
                got = len(sigs)
                sigs[sig] = got
            new_cls[state] = got
        cls = new_cls
        if len(sigs) == num:
            return num
        num = len(sigs)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    table1, acc1 = _build_dfa(p1, alphabet)
    table2, acc2 = _build_dfa(p2, alphabet)
    k = len(alphabet)
    start = (0, 0)
    parent = {start: None}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        a, b = pair
        if acc1[a] != acc2[b]:
            letters = []
            cur = pair
            while parent[cur] is not None:
                prev, idx = parent[cur]
                letters.append(alphabet[idx])
                cur = prev
            return "".join(reversed(letters))
        for idx in range(k):
            nxt = (table1[a][idx], table2[b][idx])
            if nxt not in parent:
                parent[nxt] = (pair, idx)
                queue.append(nxt)
    return None
```
