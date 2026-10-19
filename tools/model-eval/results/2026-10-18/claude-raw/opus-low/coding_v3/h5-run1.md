```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("bad alphabet")


class _NFA:
    def __init__(self):
        self.eps = []
        self.trans = []  # list of list of (frozenset(symbol indices), target)

    def new(self):
        self.eps.append([])
        self.trans.append([])
        return len(self.eps) - 1


class _Parser:
    def __init__(self, pattern, alphabet, nfa):
        self.p = pattern
        self.pos = 0
        self.alpha = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.nfa = nfa

    def peek(self):
        return self.p[self.pos] if self.pos < len(self.p) else None

    def parse(self):
        frag = self.parse_alt()
        if self.pos < len(self.p):
            raise ValueError("unbalanced )")
        return frag

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.peek() == '|':
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        start = self.nfa.new()
        end = self.nfa.new()
        for (bs, be) in branches:
            self.nfa.eps[start].append(bs)
            self.nfa.eps[be].append(end)
        return (start, end)

    def parse_seq(self):
        start = self.nfa.new()
        cur = start
        while True:
            ch = self.peek()
            if ch is None or ch == '|' or ch == ')':
                break
            if ch in '*+?':
                raise ValueError("nothing to repeat")
            frag = self.parse_atom()
            q = self.peek()
            if q is not None and q in '*+?':
                self.pos += 1
                frag = self.apply_quant(frag, q)
                q2 = self.peek()
                if q2 is not None and q2 in '*+?':
                    raise ValueError("multiple repeat")
            self.nfa.eps[cur].append(frag[0])
            cur = frag[1]
        return (start, cur)

    def apply_quant(self, frag, q):
        fs, fe = frag
        start = self.nfa.new()
        end = self.nfa.new()
        self.nfa.eps[start].append(fs)
        self.nfa.eps[fe].append(end)
        if q in '*?':
            self.nfa.eps[start].append(end)
        if q in '*+':
            self.nfa.eps[fe].append(fs)
        return (start, end)

    def char_frag(self, symbols):
        start = self.nfa.new()
        end = self.nfa.new()
        if symbols:
            self.nfa.trans[start].append((frozenset(symbols), end))
        return (start, end)

    def parse_atom(self):
        ch = self.p[self.pos]
        if ch == '(':
            self.pos += 1
            frag = self.parse_alt()
            if self.peek() != ')':
                raise ValueError("unbalanced (")
            self.pos += 1
            return frag
        if ch == '[':
            return self.char_frag(self.parse_class())
        if ch == '.':
            self.pos += 1
            return self.char_frag(set(range(len(self.alpha))))
        if ch == '\\':
            if self.pos + 1 >= len(self.p):
                raise ValueError("trailing backslash")
            c = self.p[self.pos + 1]
            self.pos += 2
        else:
            c = ch
            self.pos += 1
        syms = {self.index[c]} if c in self.index else set()
        return self.char_frag(syms)

    def class_char(self):
        if self.pos >= len(self.p):
            raise ValueError("unterminated class")
        c = self.p[self.pos]
        if c == '\\':
            if self.pos + 1 >= len(self.p):
                raise ValueError("trailing backslash")
            c = self.p[self.pos + 1]
            self.pos += 2
        else:
            self.pos += 1
        return c

    def parse_class(self):
        p = self.p
        self.pos += 1
        neg = False
        if self.pos < len(p) and p[self.pos] == '^':
            neg = True
            self.pos += 1
        chars = set()
        ranges = []
        count = 0
        while True:
            if self.pos >= len(p):
                raise ValueError("unterminated class")
            if p[self.pos] == ']':
                self.pos += 1
                break
            x = self.class_char()
            if (self.pos + 1 < len(p) and p[self.pos] == '-' and p[self.pos + 1] != ']'):
                self.pos += 1
                y = self.class_char()
                if ord(x) > ord(y):
                    raise ValueError("bad range")
                ranges.append((ord(x), ord(y)))
            else:
                chars.add(x)
            count += 1
        if count == 0:
            raise ValueError("empty class")
        result = set()
        for i, a in enumerate(self.alpha):
            inside = a in chars or any(lo <= ord(a) <= hi for lo, hi in ranges)
            if inside != neg:
                result.add(i)
        return result


def _build_dfa(pattern, alphabet):
    nfa = _NFA()
    start, end = _Parser(pattern, alphabet, nfa).parse()
    k = len(alphabet)

    def closure(states):
        stack = list(states)
        seen = set(states)
        while stack:
            s = stack.pop()
            for t in nfa.eps[s]:
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        return frozenset(seen)

    init = closure([start])
    ids = {init: 0}
    order = [init]
    delta = []
    accept = []
    i = 0
    while i < len(order):
        S = order[i]
        accept.append(end in S)
        row = []
        for sym in range(k):
            tgt = set()
            for s in S:
                for (syms, t) in nfa.trans[s]:
                    if sym in syms:
                        tgt.add(t)
            T = closure(tgt) if tgt else frozenset()
            if T not in ids:
                ids[T] = len(order)
                order.append(T)
            row.append(ids[T])
        delta.append(row)
        i += 1
    return delta, accept


def _minimize_count(delta, accept, k):
    n = len(delta)
    cls = [1 if a else 0 for a in accept]
    num = len(set(cls))
    while True:
        sigmap = {}
        newcls = [0] * n
        for s in range(n):
            sig = (cls[s],) + tuple(cls[delta[s][c]] for c in range(k))
            if sig not in sigmap:
                sigmap[sig] = len(sigmap)
            newcls[s] = sigmap[sig]
        newnum = len(sigmap)
        cls = newcls
        if newnum == num:
            return newnum
        num = newnum


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    delta, accept = _build_dfa(pattern, alphabet)
    return _minimize_count(delta, accept, len(alphabet))


def distinguish(p1: str, p2: str, alphabet: str) -> "str | None":
    _check_alphabet(alphabet)
    d1, a1 = _build_dfa(p1, alphabet)
    d2, a2 = _build_dfa(p2, alphabet)
    k = len(alphabet)
    startp = (0, 0)
    parent = {startp: None}
    queue = deque([startp])
    while queue:
        st = queue.popleft()
        x, y = st
        if a1[x] != a2[y]:
            out = []
            cur = st
            while parent[cur] is not None:
                prev, c = parent[cur]
                out.append(alphabet[c])
                cur = prev
            return ''.join(reversed(out))
        for c in range(k):
            nx = (d1[x][c], d2[y][c])
            if nx not in parent:
                parent[nx] = (st, c)
                queue.append(nx)
    return None
```
