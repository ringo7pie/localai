```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(alphabet) > 8:
        raise ValueError("invalid alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


class _NfaBuilder:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.symbol_count = len(alphabet)
        self.eps = []
        self.edges = []

    def new_state(self):
        self.eps.append([])
        self.edges.append([])
        return len(self.eps) - 1

    def parse(self):
        start, end = self.parse_alt()
        if self.pos < self.length:
            # only an unmatched ')' can stop the parser here
            raise ValueError("unbalanced parenthesis")
        return start, end

    def parse_alt(self):
        fragments = [self.parse_seq()]
        while self.pos < self.length and self.pattern[self.pos] == "|":
            self.pos += 1
            fragments.append(self.parse_seq())
        if len(fragments) == 1:
            return fragments[0]
        start = self.new_state()
        end = self.new_state()
        for frag_start, frag_end in fragments:
            self.eps[start].append(frag_start)
            self.eps[frag_end].append(end)
        return start, end

    def parse_seq(self):
        start = self.new_state()
        end = start
        while self.pos < self.length and self.pattern[self.pos] not in "|)":
            atom_start, atom_end = self.parse_atom()
            if self.pos < self.length and self.pattern[self.pos] in "*+?":
                kind = self.pattern[self.pos]
                self.pos += 1
                if self.pos < self.length and self.pattern[self.pos] in "*+?":
                    raise ValueError("repeated quantifier")
                atom_start, atom_end = self.apply_quantifier(kind, atom_start, atom_end)
            self.eps[end].append(atom_start)
            end = atom_end
        return start, end

    def apply_quantifier(self, kind, frag_start, frag_end):
        start = self.new_state()
        end = self.new_state()
        self.eps[start].append(frag_start)
        self.eps[frag_end].append(end)
        if kind in "*+":
            self.eps[frag_end].append(frag_start)
        if kind in "*?":
            self.eps[start].append(end)
        return start, end

    def symbol_fragment(self, symbols):
        start = self.new_state()
        end = self.new_state()
        if symbols:
            self.edges[start].append((tuple(symbols), end))
        return start, end

    def parse_atom(self):
        ch = self.pattern[self.pos]
        if ch in "*+?":
            raise ValueError("quantifier without target")
        if ch == "(":
            self.pos += 1
            frag = self.parse_alt()
            if self.pos >= self.length or self.pattern[self.pos] != ")":
                raise ValueError("unbalanced parenthesis")
            self.pos += 1
            return frag
        if ch == "[":
            return self.symbol_fragment(self.parse_class())
        if ch == ".":
            self.pos += 1
            return self.symbol_fragment(range(self.symbol_count))
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            literal = self.pattern[self.pos + 1]
            self.pos += 2
        else:
            literal = ch
            self.pos += 1
        found = self.index.get(literal)
        return self.symbol_fragment([] if found is None else [found])

    def read_class_char(self):
        if self.pos >= self.length:
            raise ValueError("unterminated class")
        ch = self.pattern[self.pos]
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            ch = self.pattern[self.pos + 1]
            self.pos += 2
        else:
            self.pos += 1
        return ch

    def parse_class(self):
        self.pos += 1  # '['
        negate = False
        if self.pos < self.length and self.pattern[self.pos] == "^":
            negate = True
            self.pos += 1
        ranges = []
        while True:
            if self.pos >= self.length:
                raise ValueError("unterminated class")
            if self.pattern[self.pos] == "]":
                self.pos += 1
                break
            low = self.read_class_char()
            if (
                self.pos + 1 < self.length
                and self.pattern[self.pos] == "-"
                and self.pattern[self.pos + 1] != "]"
            ):
                self.pos += 1
                high = self.read_class_char()
                if low > high:
                    raise ValueError("bad range")
                ranges.append((ord(low), ord(high)))
            else:
                ranges.append((ord(low), ord(low)))
        if not ranges:
            raise ValueError("empty class")
        symbols = []
        for symbol, ch in enumerate(self.alphabet):
            code = ord(ch)
            inside = any(lo <= code <= hi for lo, hi in ranges)
            if inside != negate:
                symbols.append(symbol)
        return symbols


def _build_dfa(pattern, alphabet):
    builder = _NfaBuilder(pattern, alphabet)
    nfa_start, nfa_end = builder.parse()
    count = len(builder.eps)
    symbol_count = len(alphabet)

    closure = [0] * count
    for state in range(count):
        seen = 1 << state
        stack = [state]
        while stack:
            current = stack.pop()
            for nxt in builder.eps[current]:
                bit = 1 << nxt
                if not seen & bit:
                    seen |= bit
                    stack.append(nxt)
        closure[state] = seen

    moves = [[0] * count for _ in range(symbol_count)]
    for state in range(count):
        for symbols, target in builder.edges[state]:
            for symbol in symbols:
                moves[symbol][state] |= closure[target]

    start_mask = closure[nfa_start]
    end_bit = 1 << nfa_end
    ids = {start_mask: 0}
    masks = [start_mask]
    delta = []
    index = 0
    while index < len(masks):
        mask = masks[index]
        index += 1
        row = []
        for symbol in range(symbol_count):
            table = moves[symbol]
            target = 0
            remaining = mask
            while remaining:
                low = remaining & -remaining
                target |= table[low.bit_length() - 1]
                remaining ^= low
            found = ids.get(target)
            if found is None:
                found = len(masks)
                ids[target] = found
                masks.append(target)
            row.append(found)
        delta.append(row)
    accept = [bool(mask & end_bit) for mask in masks]
    return _minimize(delta, accept, 0, symbol_count)


def _minimize(delta, accept, start, symbol_count):
    count = len(delta)
    inverse = [[[] for _ in range(count)] for _ in range(symbol_count)]
    for state in range(count):
        row = delta[state]
        for symbol in range(symbol_count):
            inverse[symbol][row[symbol]].append(state)

    blocks = []
    block_of = [0] * count
    for group in (
        [s for s in range(count) if accept[s]],
        [s for s in range(count) if not accept[s]],
    ):
        if group:
            block_id = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = block_id

    stack = []
    in_work = set()
    if len(blocks) == 2:
        smaller = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        stack.append(smaller)
        in_work.add(smaller)
    elif len(blocks) == 1:
        pass

    while stack:
        splitter_id = stack.pop()
        in_work.discard(splitter_id)
        splitter = list(blocks[splitter_id])
        for symbol in range(symbol_count):
            table = inverse[symbol]
            involved = {}
            for target in splitter:
                for source in table[target]:
                    involved.setdefault(block_of[source], set()).add(source)
            for block_id, part in involved.items():
                if len(part) == len(blocks[block_id]):
                    continue
                blocks[block_id] -= part
                new_id = len(blocks)
                blocks.append(part)
                for state in part:
                    block_of[state] = new_id
                if block_id in in_work:
                    stack.append(new_id)
                    in_work.add(new_id)
                else:
                    chosen = new_id if len(part) <= len(blocks[block_id]) else block_id
                    stack.append(chosen)
                    in_work.add(chosen)

    new_delta = []
    new_accept = []
    for block in blocks:
        representative = next(iter(block))
        new_delta.append([block_of[t] for t in delta[representative]])
        new_accept.append(accept[representative])
    return new_delta, new_accept, block_of[start]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    delta, _accept, _start = _build_dfa(pattern, alphabet)
    return len(delta)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    delta1, accept1, start1 = _build_dfa(p1, alphabet)
    delta2, accept2, start2 = _build_dfa(p2, alphabet)
    symbol_count = len(alphabet)
    start = (start1, start2)
    if accept1[start1] != accept2[start2]:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        first, second = current
        for symbol in range(symbol_count):
            nxt = (delta1[first][symbol], delta2[second][symbol])
            if nxt in parent:
                continue
            parent[nxt] = (current, symbol)
            if accept1[nxt[0]] != accept2[nxt[1]]:
                chars = []
                node = nxt
                while parent[node] is not None:
                    node, used = parent[node]
                    chars.append(alphabet[used])
                chars.reverse()
                return "".join(chars)
            queue.append(nxt)
    return None
```
