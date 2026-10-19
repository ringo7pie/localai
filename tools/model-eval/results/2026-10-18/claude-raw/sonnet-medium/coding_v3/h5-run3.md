```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(alphabet) > 8:
        raise ValueError("invalid alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


class _Nfa:
    def __init__(self):
        self.edges = []  # per state: list of (symbol or -1 for epsilon, target)

    def new_state(self):
        self.edges.append([])
        return len(self.edges) - 1

    def add(self, source, symbol, target):
        self.edges[source].append((symbol, target))


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.alphabet = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.pos = 0
        self.nfa = _Nfa()

    def parse(self):
        start, end = self.parse_alt()
        if self.pos < len(self.pattern):
            # only an unmatched ')' can stop parse_alt early
            raise ValueError("unmatched )")
        return self.nfa, start, end

    def symbols_fragment(self, symbols):
        nfa = self.nfa
        start = nfa.new_state()
        end = nfa.new_state()
        for symbol in symbols:
            nfa.add(start, symbol, end)
        return start, end

    def empty_fragment(self):
        nfa = self.nfa
        start = nfa.new_state()
        end = nfa.new_state()
        nfa.add(start, -1, end)
        return start, end

    def parse_alt(self):
        nfa = self.nfa
        branches = [self.parse_concat()]
        while self.pos < len(self.pattern) and self.pattern[self.pos] == "|":
            self.pos += 1
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        start = nfa.new_state()
        end = nfa.new_state()
        for branch_start, branch_end in branches:
            nfa.add(start, -1, branch_start)
            nfa.add(branch_end, -1, end)
        return start, end

    def parse_concat(self):
        nfa = self.nfa
        fragments = []
        while self.pos < len(self.pattern):
            ch = self.pattern[self.pos]
            if ch == "|" or ch == ")":
                break
            fragments.append(self.parse_quantified())
        if not fragments:
            return self.empty_fragment()
        start, end = fragments[0]
        for next_start, next_end in fragments[1:]:
            nfa.add(end, -1, next_start)
            end = next_end
        return start, end

    def parse_quantified(self):
        nfa = self.nfa
        start, end = self.parse_atom()
        if self.pos < len(self.pattern) and self.pattern[self.pos] in "*+?":
            quant = self.pattern[self.pos]
            self.pos += 1
            if self.pos < len(self.pattern) and self.pattern[self.pos] in "*+?":
                raise ValueError("repeated quantifier")
            new_start = nfa.new_state()
            new_end = nfa.new_state()
            nfa.add(new_start, -1, start)
            nfa.add(end, -1, new_end)
            if quant in "*?":
                nfa.add(new_start, -1, new_end)
            if quant in "*+":
                nfa.add(end, -1, start)
            return new_start, new_end
        return start, end

    def parse_atom(self):
        pattern = self.pattern
        ch = pattern[self.pos]
        if ch in "*+?":
            raise ValueError("nothing to repeat")
        if ch == "(":
            self.pos += 1
            fragment = self.parse_alt()
            if self.pos >= len(pattern) or pattern[self.pos] != ")":
                raise ValueError("unclosed (")
            self.pos += 1
            return fragment
        if ch == ".":
            self.pos += 1
            return self.symbols_fragment(range(len(self.alphabet)))
        if ch == "\\":
            if self.pos + 1 >= len(pattern):
                raise ValueError("trailing backslash")
            literal = pattern[self.pos + 1]
            self.pos += 2
            return self.literal_fragment(literal)
        if ch == "[":
            return self.parse_class()
        self.pos += 1
        return self.literal_fragment(ch)

    def literal_fragment(self, ch):
        if ch in self.index:
            return self.symbols_fragment([self.index[ch]])
        return self.symbols_fragment([])

    def read_class_char(self):
        pattern = self.pattern
        if self.pos >= len(pattern):
            raise ValueError("unclosed [")
        ch = pattern[self.pos]
        if ch == "\\":
            if self.pos + 1 >= len(pattern):
                raise ValueError("unclosed [")
            ch = pattern[self.pos + 1]
            self.pos += 2
        else:
            self.pos += 1
        return ch

    def parse_class(self):
        pattern = self.pattern
        self.pos += 1  # '['
        negate = False
        if self.pos < len(pattern) and pattern[self.pos] == "^":
            negate = True
            self.pos += 1
        ranges = []
        while True:
            if self.pos >= len(pattern):
                raise ValueError("unclosed [")
            if pattern[self.pos] == "]":
                self.pos += 1
                break
            low = self.read_class_char()
            if (
                self.pos + 1 < len(pattern)
                and pattern[self.pos] == "-"
                and pattern[self.pos + 1] != "]"
            ):
                self.pos += 1
                high = self.read_class_char()
                if low > high:
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                ranges.append((low, low))
        if not ranges:
            raise ValueError("empty class")
        symbols = []
        for i, ch in enumerate(self.alphabet):
            inside = any(low <= ch <= high for low, high in ranges)
            if inside != negate:
                symbols.append(i)
        return self.symbols_fragment(symbols)


def _build_dfa(pattern, alphabet):
    """Return (transitions, accepting, start) of a complete DFA (not minimized)."""
    _check_alphabet(alphabet)
    parser = _Parser(pattern, alphabet)
    nfa, nfa_start, nfa_end = parser.parse()
    edges = nfa.edges
    symbol_count = len(alphabet)

    closure_cache = {}

    def closure(states):
        stack = list(states)
        seen = set(states)
        while stack:
            current = stack.pop()
            for symbol, target in edges[current]:
                if symbol == -1 and target not in seen:
                    seen.add(target)
                    stack.append(target)
        return frozenset(seen)

    start_set = closure([nfa_start])
    ids = {start_set: 0}
    subsets = [start_set]
    transitions = []
    index = 0
    while index < len(subsets):
        subset = subsets[index]
        row = []
        for symbol in range(symbol_count):
            targets = set()
            for state in subset:
                for edge_symbol, target in edges[state]:
                    if edge_symbol == symbol:
                        targets.add(target)
            key = frozenset(targets)
            if key in closure_cache:
                next_set = closure_cache[key]
            else:
                next_set = closure(targets)
                closure_cache[key] = next_set
            if next_set not in ids:
                ids[next_set] = len(subsets)
                subsets.append(next_set)
            row.append(ids[next_set])
        transitions.append(row)
        index += 1
    accepting = [nfa_end in subset for subset in subsets]
    return transitions, accepting, 0


def _minimize(transitions, accepting, start):
    """Hopcroft minimization. Returns (transitions, accepting, start)."""
    state_count = len(transitions)
    symbol_count = len(transitions[0])
    inverse = [[[] for _ in range(state_count)] for _ in range(symbol_count)]
    for source in range(state_count):
        for symbol in range(symbol_count):
            inverse[symbol][transitions[source][symbol]].append(source)

    accept_set = {s for s in range(state_count) if accepting[s]}
    reject_set = set(range(state_count)) - accept_set
    blocks = []
    for group in (accept_set, reject_set):
        if group:
            blocks.append(group)
    block_of = [0] * state_count
    for block_id, group in enumerate(blocks):
        for state in group:
            block_of[state] = block_id

    if len(blocks) == 2:
        smaller = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        work = {smaller}
    else:
        work = set()

    while work:
        splitter_id = work.pop()
        splitter = list(blocks[splitter_id])
        for symbol in range(symbol_count):
            sources = set()
            table = inverse[symbol]
            for state in splitter:
                sources.update(table[state])
            if not sources:
                continue
            touched = {}
            for state in sources:
                touched.setdefault(block_of[state], set()).add(state)
            for block_id, inside in touched.items():
                block = blocks[block_id]
                if len(inside) == len(block):
                    continue
                outside = block - inside
                if len(inside) <= len(outside):
                    moved, kept = inside, outside
                else:
                    moved, kept = outside, inside
                new_id = len(blocks)
                blocks[block_id] = kept
                blocks.append(moved)
                for state in moved:
                    block_of[state] = new_id
                if block_id in work:
                    work.add(new_id)
                else:
                    work.add(new_id)

    new_transitions = []
    new_accepting = []
    for group in blocks:
        representative = next(iter(group))
        new_transitions.append(
            [block_of[transitions[representative][symbol]] for symbol in range(symbol_count)]
        )
        new_accepting.append(accepting[representative])
    return new_transitions, new_accepting, block_of[start]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    transitions, accepting, start = _build_dfa(pattern, alphabet)
    minimized, _, _ = _minimize(transitions, accepting, start)
    return len(minimized)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    dfa1 = _build_dfa(p1, alphabet)
    dfa2 = _build_dfa(p2, alphabet)
    trans1, acc1, start1 = _minimize(*dfa1)
    trans2, acc2, start2 = _minimize(*dfa2)
    symbol_count = len(alphabet)

    start = (start1, start2)
    if acc1[start1] != acc2[start2]:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        state1, state2 = pair
        for symbol in range(symbol_count):
            nxt = (trans1[state1][symbol], trans2[state2][symbol])
            if nxt in parent:
                continue
            parent[nxt] = (pair, symbol)
            if acc1[nxt[0]] != acc2[nxt[1]]:
                chars = []
                node = nxt
                while parent[node] is not None:
                    previous, used = parent[node]
                    chars.append(alphabet[used])
                    node = previous
                return "".join(reversed(chars))
            queue.append(nxt)
    return None
```
