```python
def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("invalid alphabet")
    if len(alphabet) > 8:
        raise ValueError("alphabet too long")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.full = frozenset(range(len(alphabet)))

    def parse(self):
        node = self.parse_alt()
        if self.pos != self.length:
            raise ValueError("unbalanced )")
        return node

    def parse_alt(self):
        branches = [self.parse_concat()]
        while self.pos < self.length and self.pattern[self.pos] == "|":
            self.pos += 1
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def literal(self, ch):
        idx = self.index.get(ch)
        if idx is None:
            return ("set", frozenset())
        return ("set", frozenset((idx,)))

    def parse_concat(self):
        items = []
        pattern = self.pattern
        while self.pos < self.length:
            ch = pattern[self.pos]
            if ch == "|" or ch == ")":
                break
            if ch in "*+?":
                raise ValueError("nothing to repeat")
            if ch == "(":
                self.pos += 1
                node = self.parse_alt()
                if self.pos >= self.length or pattern[self.pos] != ")":
                    raise ValueError("unbalanced (")
                self.pos += 1
            elif ch == "[":
                node = self.parse_class()
            elif ch == ".":
                self.pos += 1
                node = ("set", self.full)
            elif ch == "\\":
                if self.pos + 1 >= self.length:
                    raise ValueError("trailing backslash")
                node = self.literal(pattern[self.pos + 1])
                self.pos += 2
            else:
                node = self.literal(ch)
                self.pos += 1
            if self.pos < self.length and pattern[self.pos] in "*+?":
                kind = {"*": "star", "+": "plus", "?": "opt"}[pattern[self.pos]]
                node = (kind, node)
                self.pos += 1
                if self.pos < self.length and pattern[self.pos] in "*+?":
                    raise ValueError("multiple repeat")
            items.append(node)
        if not items:
            return ("empty",)
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def read_class_char(self):
        pattern = self.pattern
        ch = pattern[self.pos]
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            ch = pattern[self.pos + 1]
            self.pos += 2
        else:
            self.pos += 1
        return ch

    def parse_class(self):
        pattern = self.pattern
        self.pos += 1  # '['
        negate = False
        if self.pos < self.length and pattern[self.pos] == "^":
            negate = True
            self.pos += 1
        members = set()
        count = 0
        while True:
            if self.pos >= self.length:
                raise ValueError("unterminated class")
            if pattern[self.pos] == "]":
                break
            low = self.read_class_char()
            if (
                self.pos + 1 < self.length
                and pattern[self.pos] == "-"
                and pattern[self.pos + 1] != "]"
            ):
                self.pos += 1
                high = self.read_class_char()
                if low > high:
                    raise ValueError("bad range")
                for idx, letter in enumerate(self.alphabet):
                    if low <= letter <= high:
                        members.add(idx)
            else:
                idx = self.index.get(low)
                if idx is not None:
                    members.add(idx)
            count += 1
        if count == 0:
            raise ValueError("empty class")
        self.pos += 1  # ']'
        if negate:
            return ("set", frozenset(self.full - members))
        return ("set", frozenset(members))


class _NFA:
    def __init__(self):
        self.eps = []
        self.moves = []

    def new_state(self):
        self.eps.append([])
        self.moves.append([])
        return len(self.eps) - 1

    def build(self, node):
        kind = node[0]
        if kind == "empty":
            state = self.new_state()
            return state, state
        if kind == "set":
            start = self.new_state()
            end = self.new_state()
            self.moves[start].append((node[1], end))
            return start, end
        if kind == "cat":
            start, end = self.build(node[1][0])
            for child in node[1][1:]:
                child_start, child_end = self.build(child)
                self.eps[end].append(child_start)
                end = child_end
            return start, end
        if kind == "alt":
            start = self.new_state()
            end = self.new_state()
            for child in node[1]:
                child_start, child_end = self.build(child)
                self.eps[start].append(child_start)
                self.eps[child_end].append(end)
            return start, end
        inner_start, inner_end = self.build(node[1])
        start = self.new_state()
        end = self.new_state()
        self.eps[start].append(inner_start)
        self.eps[inner_end].append(end)
        if kind == "star":
            self.eps[start].append(end)
            self.eps[inner_end].append(inner_start)
        elif kind == "plus":
            self.eps[inner_end].append(inner_start)
        elif kind == "opt":
            self.eps[start].append(end)
        return start, end


def _minimize(trans, accepting, symbol_count):
    count = len(trans)
    inverse = [[[] for _ in range(count)] for _ in range(symbol_count)]
    for state in range(count):
        row = trans[state]
        for symbol in range(symbol_count):
            inverse[symbol][row[symbol]].append(state)

    accept_set = set(s for s in range(count) if accepting[s])
    reject_set = set(s for s in range(count) if not accepting[s])
    blocks = []
    for group in (accept_set, reject_set):
        if group:
            blocks.append(group)
    block_of = [0] * count
    for block_id, group in enumerate(blocks):
        for state in group:
            block_of[state] = block_id
    work = set()
    if len(blocks) == 2:
        work.add(0 if len(blocks[0]) <= len(blocks[1]) else 1)

    while work:
        splitter_id = work.pop()
        splitter = list(blocks[splitter_id])
        for symbol in range(symbol_count):
            inv_symbol = inverse[symbol]
            predecessors = set()
            for target in splitter:
                predecessors.update(inv_symbol[target])
            touched = {}
            for state in predecessors:
                touched.setdefault(block_of[state], []).append(state)
            for block_id, members in touched.items():
                if len(members) == len(blocks[block_id]):
                    continue
                new_block = set(members)
                blocks[block_id].difference_update(new_block)
                new_id = len(blocks)
                blocks.append(new_block)
                for state in members:
                    block_of[state] = new_id
                if block_id in work:
                    work.add(new_id)
                elif len(blocks[block_id]) <= len(new_block):
                    work.add(block_id)
                else:
                    work.add(new_id)

    new_trans = []
    new_accepting = []
    for group in blocks:
        rep = next(iter(group))
        new_trans.append([block_of[trans[rep][symbol]] for symbol in range(symbol_count)])
        new_accepting.append(accepting[rep])
    return new_trans, new_accepting, block_of[0]


def _build_dfa(pattern, alphabet):
    _check_alphabet(alphabet)
    if not isinstance(pattern, str):
        raise ValueError("pattern must be str")
    symbol_count = len(alphabet)
    ast = _Parser(pattern, alphabet).parse()
    nfa = _NFA()
    nfa_start, nfa_end = nfa.build(ast)
    size = len(nfa.eps)

    closure = [0] * size
    for state in range(size):
        seen = 1 << state
        stack = [state]
        while stack:
            current = stack.pop()
            for nxt in nfa.eps[current]:
                bit = 1 << nxt
                if not seen & bit:
                    seen |= bit
                    stack.append(nxt)
        closure[state] = seen

    step = [[0] * size for _ in range(symbol_count)]
    movable = 0
    for state in range(size):
        if nfa.moves[state]:
            movable |= 1 << state
        for charset, target in nfa.moves[state]:
            for symbol in charset:
                step[symbol][state] |= closure[target]

    start_mask = closure[nfa_start]
    ids = {start_mask: 0}
    masks = [start_mask]
    trans = []
    index = 0
    while index < len(masks):
        mask = masks[index]
        active = mask & movable
        row = []
        for symbol in range(symbol_count):
            step_symbol = step[symbol]
            new_mask = 0
            rest = active
            while rest:
                low = rest & -rest
                new_mask |= step_symbol[low.bit_length() - 1]
                rest ^= low
            target = ids.get(new_mask)
            if target is None:
                target = len(masks)
                ids[new_mask] = target
                masks.append(new_mask)
            row.append(target)
        trans.append(row)
        index += 1
    accepting = [bool((mask >> nfa_end) & 1) for mask in masks]
    return _minimize(trans, accepting, symbol_count)


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    trans, _accepting, _start = _build_dfa(pattern, alphabet)
    return len(trans)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    trans1, accept1, start1 = _build_dfa(p1, alphabet)
    trans2, accept2, start2 = _build_dfa(p2, alphabet)
    symbol_count = len(alphabet)
    if accept1[start1] != accept2[start2]:
        return ""
    width = len(trans2)
    nodes = [(start1, start2)]
    parents = [-1]
    symbols = [-1]
    seen = {start1 * width + start2}
    index = 0
    while index < len(nodes):
        left, right = nodes[index]
        row1 = trans1[left]
        row2 = trans2[right]
        for symbol in range(symbol_count):
            next_left = row1[symbol]
            next_right = row2[symbol]
            key = next_left * width + next_right
            if key in seen:
                continue
            seen.add(key)
            nodes.append((next_left, next_right))
            parents.append(index)
            symbols.append(symbol)
            if accept1[next_left] != accept2[next_right]:
                letters = []
                cursor = len(nodes) - 1
                while parents[cursor] != -1:
                    letters.append(alphabet[symbols[cursor]])
                    cursor = parents[cursor]
                letters.reverse()
                return "".join(letters)
        index += 1
    return None
```
