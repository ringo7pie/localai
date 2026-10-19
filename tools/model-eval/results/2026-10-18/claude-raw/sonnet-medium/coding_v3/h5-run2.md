```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("invalid alphabet")


class _Nfa:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.alphabet = alphabet
        self.alpha_set = set(alphabet)
        self.pos = 0
        self.eps = []
        self.trans = []
        frag = self._parse_alt()
        if self.pos < len(pattern):
            raise ValueError("unmatched )")
        self.start, self.end = frag
        self._build_tables()

    def _new(self):
        self.eps.append([])
        self.trans.append({})
        return len(self.eps) - 1

    def _peek(self):
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def _charset_frag(self, chars):
        s = self._new()
        e = self._new()
        for ch in chars:
            if ch in self.alpha_set:
                self.trans[s].setdefault(ch, []).append(e)
        return (s, e)

    def _parse_alt(self):
        frags = [self._parse_seq()]
        while self._peek() == "|":
            self.pos += 1
            frags.append(self._parse_seq())
        if len(frags) == 1:
            return frags[0]
        s = self._new()
        e = self._new()
        for fs, fe in frags:
            self.eps[s].append(fs)
            self.eps[fe].append(e)
        return (s, e)

    def _parse_seq(self):
        s = self._new()
        cur_end = s
        while True:
            ch = self._peek()
            if ch is None or ch == "|" or ch == ")":
                break
            if ch in "*+?":
                raise ValueError("nothing to repeat")
            atom = self._parse_atom()
            q = self._peek()
            if q is not None and q in "*+?":
                self.pos += 1
                atom = self._quantify(atom, q)
                q2 = self._peek()
                if q2 is not None and q2 in "*+?":
                    raise ValueError("multiple repeat")
            self.eps[cur_end].append(atom[0])
            cur_end = atom[1]
        return (s, cur_end)

    def _quantify(self, frag, q):
        fs, fe = frag
        s = self._new()
        e = self._new()
        self.eps[s].append(fs)
        self.eps[fe].append(e)
        if q in "*?":
            self.eps[s].append(e)
        if q in "*+":
            self.eps[fe].append(fs)
        return (s, e)

    def _parse_atom(self):
        ch = self.pattern[self.pos]
        if ch == "(":
            self.pos += 1
            frag = self._parse_alt()
            if self._peek() != ")":
                raise ValueError("missing )")
            self.pos += 1
            return frag
        if ch == "[":
            self.pos += 1
            return self._parse_class()
        if ch == ".":
            self.pos += 1
            return self._charset_frag(self.alphabet)
        if ch == "\\":
            if self.pos + 1 >= len(self.pattern):
                raise ValueError("trailing backslash")
            lit = self.pattern[self.pos + 1]
            self.pos += 2
            return self._charset_frag(lit)
        self.pos += 1
        return self._charset_frag(ch)

    def _read_class_char(self):
        pat = self.pattern
        if self.pos >= len(pat):
            raise ValueError("unclosed class")
        ch = pat[self.pos]
        if ch == "\\":
            if self.pos + 1 >= len(pat):
                raise ValueError("trailing backslash")
            self.pos += 2
            return pat[self.pos - 1]
        self.pos += 1
        return ch

    def _parse_class(self):
        pat = self.pattern
        negate = False
        if self.pos < len(pat) and pat[self.pos] == "^":
            negate = True
            self.pos += 1
        ranges = []
        while True:
            if self.pos >= len(pat):
                raise ValueError("unclosed class")
            if pat[self.pos] == "]":
                self.pos += 1
                break
            low = self._read_class_char()
            if (
                self.pos + 1 < len(pat)
                and pat[self.pos] == "-"
                and pat[self.pos + 1] != "]"
            ):
                self.pos += 1
                high = self._read_class_char()
                if low > high:
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                ranges.append((low, low))
        if not ranges:
            raise ValueError("empty class")
        chosen = []
        for ch in self.alphabet:
            inside = any(lo <= ch <= hi for lo, hi in ranges)
            if inside != negate:
                chosen.append(ch)
        return self._charset_frag(chosen)

    def _build_tables(self):
        count = len(self.eps)
        closure = [0] * count
        for state in range(count):
            seen = 1 << state
            stack = [state]
            while stack:
                cur = stack.pop()
                for nxt in self.eps[cur]:
                    if not (seen >> nxt) & 1:
                        seen |= 1 << nxt
                        stack.append(nxt)
            closure[state] = seen
        self.closure = closure
        self.move = []
        for ch in self.alphabet:
            row = [0] * count
            for state in range(count):
                targets = self.trans[state].get(ch)
                if targets:
                    mask = 0
                    for target in targets:
                        mask |= closure[target]
                    row[state] = mask
            self.move.append(row)
        self.start_mask = closure[self.start]
        self.cache = {}

    def accepts(self, mask):
        return (mask >> self.end) & 1 == 1

    def step(self, mask, index):
        key = (mask, index)
        got = self.cache.get(key)
        if got is not None:
            return got
        row = self.move[index]
        result = 0
        rest = mask
        while rest:
            low = rest & -rest
            result |= row[low.bit_length() - 1]
            rest ^= low
        self.cache[key] = result
        return result


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    nfa = _Nfa(pattern, alphabet)
    size = len(alphabet)
    ids = {nfa.start_mask: 0}
    masks = [nfa.start_mask]
    delta = []
    index = 0
    while index < len(masks):
        mask = masks[index]
        row = []
        for ci in range(size):
            nxt = nfa.step(mask, ci)
            found = ids.get(nxt)
            if found is None:
                found = len(masks)
                ids[nxt] = found
                masks.append(nxt)
            row.append(found)
        delta.append(row)
        index += 1
    count = len(masks)
    inverse = [[[] for _ in range(count)] for _ in range(size)]
    for state in range(count):
        for ci in range(size):
            inverse[ci][delta[state][ci]].append(state)
    accepting = set(s for s in range(count) if nfa.accepts(masks[s]))
    rejecting = set(range(count)) - accepting
    blocks = []
    for group in (accepting, rejecting):
        if group:
            blocks.append(group)
    block_of = [0] * count
    for bid, group in enumerate(blocks):
        for state in group:
            block_of[state] = bid
    if len(blocks) == 1:
        return 1
    in_work = [True] * len(blocks)
    work = list(range(len(blocks)))
    while work:
        a_id = work.pop()
        in_work[a_id] = False
        splitter = list(blocks[a_id])
        for ci in range(size):
            hit = {}
            inv = inverse[ci]
            for target in splitter:
                for source in inv[target]:
                    hit.setdefault(block_of[source], set()).add(source)
            for bid, inter in hit.items():
                whole = blocks[bid]
                if len(inter) == len(whole):
                    continue
                rest = whole - inter
                if len(inter) <= len(rest):
                    small, large = inter, rest
                else:
                    small, large = rest, inter
                new_id = len(blocks)
                blocks[bid] = large
                blocks.append(small)
                in_work.append(False)
                for state in small:
                    block_of[state] = new_id
                if in_work[bid]:
                    in_work[new_id] = True
                    work.append(new_id)
                else:
                    in_work[new_id] = True
                    work.append(new_id)
    return len(blocks)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    left = _Nfa(p1, alphabet)
    right = _Nfa(p2, alphabet)
    size = len(alphabet)
    start = (left.start_mask, right.start_mask)
    if left.accepts(start[0]) != right.accepts(start[1]):
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for ci in range(size):
            nxt = (left.step(current[0], ci), right.step(current[1], ci))
            if nxt in parent:
                continue
            parent[nxt] = (current, ci)
            if left.accepts(nxt[0]) != right.accepts(nxt[1]):
                chars = []
                node = nxt
                while parent[node] is not None:
                    prev, pci = parent[node]
                    chars.append(alphabet[pci])
                    node = prev
                chars.reverse()
                return "".join(chars)
            queue.append(nxt)
    return None
```
