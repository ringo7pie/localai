```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) < 1 or len(alphabet) > 8:
        raise ValueError("invalid alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.p = pattern
        self.n = len(pattern)
        self.i = 0
        self.alphabet = alphabet

    def parse(self):
        node = self.parse_alt()
        if self.i < self.n:
            # only an unmatched ')' can stop the top-level parse
            raise ValueError("unmatched )")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.i < self.n and self.p[self.i] == '|':
            self.i += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def parse_seq(self):
        items = []
        while self.i < self.n and self.p[self.i] not in '|)':
            ch = self.p[self.i]
            if ch in '*+?':
                raise ValueError("nothing to repeat")
            atom = self.parse_atom()
            if self.i < self.n and self.p[self.i] in '*+?':
                q = self.p[self.i]
                self.i += 1
                if q == '*':
                    atom = ('star', atom)
                elif q == '+':
                    atom = ('plus', atom)
                else:
                    atom = ('opt', atom)
                if self.i < self.n and self.p[self.i] in '*+?':
                    raise ValueError("repeated quantifier")
            items.append(atom)
        if not items:
            return ('eps',)
        if len(items) == 1:
            return items[0]
        return ('cat', items)

    def parse_atom(self):
        ch = self.p[self.i]
        if ch == '(':
            self.i += 1
            node = self.parse_alt()
            if self.i >= self.n or self.p[self.i] != ')':
                raise ValueError("unmatched (")
            self.i += 1
            return node
        if ch == '[':
            return self.parse_class()
        if ch == '.':
            self.i += 1
            return ('set', frozenset(self.alphabet))
        if ch == '\\':
            if self.i + 1 >= self.n:
                raise ValueError("trailing backslash")
            lit = self.p[self.i + 1]
            self.i += 2
            return ('set', frozenset(c for c in (lit,) if c in self.alphabet))
        self.i += 1
        return ('set', frozenset(c for c in (ch,) if c in self.alphabet))

    def read_class_char(self):
        if self.i >= self.n:
            raise ValueError("unclosed class")
        ch = self.p[self.i]
        if ch == '\\':
            if self.i + 1 >= self.n:
                raise ValueError("trailing backslash")
            self.i += 2
            return self.p[self.i - 1]
        self.i += 1
        return ch

    def parse_class(self):
        self.i += 1  # skip [
        negate = False
        if self.i < self.n and self.p[self.i] == '^':
            negate = True
            self.i += 1
        chosen = set()
        count = 0
        while True:
            if self.i >= self.n:
                raise ValueError("unclosed class")
            if self.p[self.i] == ']':
                self.i += 1
                break
            low = self.read_class_char()
            if (self.i + 1 < self.n and self.p[self.i] == '-'
                    and self.p[self.i + 1] != ']'):
                self.i += 1
                high = self.read_class_char()
                if low > high:
                    raise ValueError("bad range")
                for c in self.alphabet:
                    if low <= c <= high:
                        chosen.add(c)
            else:
                if low in self.alphabet:
                    chosen.add(low)
            count += 1
        if count == 0:
            raise ValueError("empty class")
        if negate:
            chosen = set(c for c in self.alphabet if c not in chosen)
        return ('set', frozenset(chosen))


class _NFA:
    def __init__(self):
        self.eps = []
        self.trans = []

    def new(self):
        self.eps.append([])
        self.trans.append({})
        return len(self.eps) - 1

    def build(self, node):
        kind = node[0]
        start = self.new()
        end = self.new()
        if kind == 'eps':
            self.eps[start].append(end)
        elif kind == 'set':
            for ch in node[1]:
                self.trans[start].setdefault(ch, []).append(end)
        elif kind == 'cat':
            prev_end = start
            for child in node[1]:
                cs, ce = self.build(child)
                self.eps[prev_end].append(cs)
                prev_end = ce
            self.eps[prev_end].append(end)
        elif kind == 'alt':
            for child in node[1]:
                cs, ce = self.build(child)
                self.eps[start].append(cs)
                self.eps[ce].append(end)
        elif kind == 'star':
            cs, ce = self.build(node[1])
            self.eps[start].extend([cs, end])
            self.eps[ce].extend([cs, end])
        elif kind == 'plus':
            cs, ce = self.build(node[1])
            self.eps[start].append(cs)
            self.eps[ce].extend([cs, end])
        elif kind == 'opt':
            cs, ce = self.build(node[1])
            self.eps[start].extend([cs, end])
            self.eps[ce].append(end)
        return start, end


def _build_dfa(pattern, alphabet):
    _check_alphabet(alphabet)
    if not isinstance(pattern, str):
        raise ValueError("pattern must be str")
    ast = _Parser(pattern, alphabet).parse()
    nfa = _NFA()
    nfa_start, nfa_end = nfa.build(ast)
    count = len(nfa.eps)
    closures = []
    for state in range(count):
        seen = {state}
        stack = [state]
        while stack:
            cur = stack.pop()
            for nxt in nfa.eps[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        closures.append(frozenset(seen))

    start_set = closures[nfa_start]
    index = {start_set: 0}
    subsets = [start_set]
    table = []
    queue = deque([0])
    while queue:
        sid = queue.popleft()
        subset = subsets[sid]
        row = []
        for ch in alphabet:
            targets = set()
            for st in subset:
                dests = nfa.trans[st].get(ch)
                if dests:
                    for dest in dests:
                        targets |= closures[dest]
            target = frozenset(targets)
            tid = index.get(target)
            if tid is None:
                tid = len(subsets)
                index[target] = tid
                subsets.append(target)
                queue.append(tid)
            row.append(tid)
        while len(table) <= sid:
            table.append(None)
        table[sid] = row
    accepting = [nfa_end in subset for subset in subsets]
    return table, accepting


def _minimize_count(table, accepting):
    size = len(table)
    block = [1 if accepting[s] else 0 for s in range(size)]
    num_blocks = len(set(block))
    while True:
        sig_index = {}
        new_block = [0] * size
        for s in range(size):
            sig = (block[s],) + tuple(block[t] for t in table[s])
            bid = sig_index.get(sig)
            if bid is None:
                bid = len(sig_index)
                sig_index[sig] = bid
            new_block[s] = bid
        new_count = len(sig_index)
        block = new_block
        if new_count == num_blocks:
            return new_count
        num_blocks = new_count


def min_dfa_size(pattern: str, alphabet: str) -> int:
    table, accepting = _build_dfa(pattern, alphabet)
    return _minimize_count(table, accepting)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    table1, acc1 = _build_dfa(p1, alphabet)
    table2, acc2 = _build_dfa(p2, alphabet)
    letters = len(alphabet)
    start = (0, 0)
    parent = {start: None}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        first, second = pair
        if acc1[first] != acc2[second]:
            chars = []
            cur = pair
            while parent[cur] is not None:
                prev, ch = parent[cur]
                chars.append(ch)
                cur = prev
            chars.reverse()
            return ''.join(chars)
        row1 = table1[first]
        row2 = table2[second]
        for k in range(letters):
            nxt = (row1[k], row2[k])
            if nxt not in parent:
                parent[nxt] = (pair, alphabet[k])
                queue.append(nxt)
    return None
```
