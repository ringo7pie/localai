```python
def _check_alphabet(alphabet):
    letters = list(alphabet)
    if not letters or len(set(letters)) != len(letters):
        raise ValueError("invalid alphabet")
    return letters


class _Parser:
    def __init__(self, pattern, letters):
        self.p = pattern
        self.i = 0
        self.letters = letters
        self.full = frozenset(range(len(letters)))
        self.index = {ch: n for n, ch in enumerate(letters)}

    def parse(self):
        node = self.alt()
        if self.i < len(self.p):
            raise ValueError("unmatched )")
        return node

    def alt(self):
        branches = [self.seq()]
        while self.i < len(self.p) and self.p[self.i] == '|':
            self.i += 1
            branches.append(self.seq())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def seq(self):
        items = []
        while self.i < len(self.p) and self.p[self.i] not in '|)':
            node = self.atom()
            if self.i < len(self.p) and self.p[self.i] in '*+?':
                kind = {'*': 'star', '+': 'plus', '?': 'opt'}[self.p[self.i]]
                self.i += 1
                node = (kind, node)
                if self.i < len(self.p) and self.p[self.i] in '*+?':
                    raise ValueError("repeated quantifier")
            items.append(node)
        if not items:
            return ('eps',)
        if len(items) == 1:
            return items[0]
        return ('cat', items)

    def literal(self, ch):
        n = self.index.get(ch)
        if n is None:
            return frozenset()
        return frozenset((n,))

    def atom(self):
        ch = self.p[self.i]
        if ch == '(':
            self.i += 1
            node = self.alt()
            if self.i >= len(self.p) or self.p[self.i] != ')':
                raise ValueError("unclosed (")
            self.i += 1
            return node
        if ch in '*+?':
            raise ValueError("nothing to repeat")
        if ch == '[':
            return self.char_class()
        if ch == '.':
            self.i += 1
            return ('set', self.full)
        if ch == '\\':
            if self.i + 1 >= len(self.p):
                raise ValueError("trailing backslash")
            ch = self.p[self.i + 1]
            self.i += 2
        else:
            self.i += 1
        return ('set', self.literal(ch))

    def read_char(self):
        text = self.p
        if self.i >= len(text):
            raise ValueError("unclosed [")
        ch = text[self.i]
        if ch == '\\':
            if self.i + 1 >= len(text):
                raise ValueError("trailing backslash")
            ch = text[self.i + 1]
            self.i += 2
        else:
            self.i += 1
        return ch

    def char_class(self):
        text = self.p
        self.i += 1
        negate = False
        if self.i < len(text) and text[self.i] == '^':
            negate = True
            self.i += 1
        ranges = []
        while True:
            if self.i >= len(text):
                raise ValueError("unclosed [")
            if text[self.i] == ']':
                if not ranges:
                    raise ValueError("empty class")
                self.i += 1
                break
            low = self.read_char()
            high = low
            if (self.i + 1 < len(text) and text[self.i] == '-'
                    and text[self.i + 1] != ']'):
                self.i += 1
                high = self.read_char()
                if low > high:
                    raise ValueError("bad range")
            ranges.append((ord(low), ord(high)))
        members = frozenset(
            n for n, ch in enumerate(self.letters)
            if any(lo <= ord(ch) <= hi for lo, hi in ranges)
        )
        if negate:
            members = self.full - members
        return ('set', members)


def _build_dfa(pattern, letters):
    ast = _Parser(pattern, letters).parse()
    width = len(letters)
    eps = []
    edges = []

    def new_state():
        eps.append([])
        edges.append([])
        return len(eps) - 1

    def build(node):
        kind = node[0]
        if kind == 'set':
            first = new_state()
            last = new_state()
            if node[1]:
                edges[first].append((node[1], last))
            return first, last
        if kind == 'eps':
            first = new_state()
            last = new_state()
            eps[first].append(last)
            return first, last
        if kind == 'cat':
            first, last = build(node[1][0])
            for child in node[1][1:]:
                child_first, child_last = build(child)
                eps[last].append(child_first)
                last = child_last
            return first, last
        if kind == 'alt':
            first = new_state()
            last = new_state()
            for child in node[1]:
                child_first, child_last = build(child)
                eps[first].append(child_first)
                eps[child_last].append(last)
            return first, last
        child_first, child_last = build(node[1])
        first = new_state()
        last = new_state()
        eps[first].append(child_first)
        eps[child_last].append(last)
        if kind in ('star', 'plus'):
            eps[child_last].append(child_first)
        if kind in ('star', 'opt'):
            eps[first].append(last)
        return first, last

    start, final = build(ast)
    count = len(eps)

    closure = [0] * count
    for state in range(count):
        seen = 1 << state
        stack = [state]
        while stack:
            current = stack.pop()
            for nxt in eps[current]:
                bit = 1 << nxt
                if not seen & bit:
                    seen |= bit
                    stack.append(nxt)
        closure[state] = seen

    important = 1 << final
    for state in range(count):
        if edges[state]:
            important |= 1 << state
    step = {}
    for state in range(count):
        if edges[state]:
            row = []
            for letter in range(width):
                mask = 0
                for letter_set, target in edges[state]:
                    if letter in letter_set:
                        mask |= closure[target]
                row.append(mask & important)
            step[state] = row

    start_mask = closure[start] & important
    ids = {start_mask: 0}
    order = [start_mask]
    cols = [[] for _ in range(width)]
    accepting = []
    final_bit = 1 << final
    position = 0
    while position < len(order):
        mask = order[position]
        position += 1
        accepting.append(bool(mask & final_bit))
        acc = [0] * width
        rest = mask
        while rest:
            low = rest & -rest
            rest ^= low
            row = step.get(low.bit_length() - 1)
            if row is not None:
                for letter in range(width):
                    acc[letter] |= row[letter]
        for letter in range(width):
            nxt = acc[letter]
            target = ids.get(nxt)
            if target is None:
                target = len(order)
                ids[nxt] = target
                order.append(nxt)
            cols[letter].append(target)
    return cols, accepting


def _moore(cols, accepting, keep_history):
    cls = [1 if flag else 0 for flag in accepting]
    count = len(set(cls))
    history = [cls]
    while True:
        sigs = zip(cls, *[[cls[x] for x in col] for col in cols])
        table = {}
        new = [table.setdefault(sig, len(table)) for sig in sigs]
        if len(table) == count:
            break
        cls = new
        count = len(table)
        if keep_history:
            history.append(cls)
    return cls, count, history


def _minimal(pattern, alphabet):
    letters = _check_alphabet(alphabet)
    cols, accepting = _build_dfa(pattern, letters)
    cls, count, _ = _moore(cols, accepting, False)
    qcols = [[0] * count for _ in cols]
    qacc = [False] * count
    for state, group in enumerate(cls):
        qacc[group] = accepting[state]
        for letter, col in enumerate(cols):
            qcols[letter][group] = cls[col[state]]
    return letters, cls[0], qcols, qacc


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _, _, _, qacc = _minimal(pattern, alphabet)
    return len(qacc)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    letters = _check_alphabet(alphabet)
    _, start1, cols1, acc1 = _minimal(p1, alphabet)
    _, start2, cols2, acc2 = _minimal(p2, alphabet)
    offset = len(acc1)
    cols = [cols1[c] + [x + offset for x in cols2[c]] for c in range(len(letters))]
    accepting = acc1 + acc2
    _, _, history = _moore(cols, accepting, True)
    state_a = start1
    state_b = start2 + offset
    final = history[-1]
    if final[state_a] == final[state_b]:
        return None
    depth = 0
    while history[depth][state_a] == history[depth][state_b]:
        depth += 1
    result = []
    while depth > 0:
        previous = history[depth - 1]
        for letter in range(len(letters)):
            next_a = cols[letter][state_a]
            next_b = cols[letter][state_b]
            if previous[next_a] != previous[next_b]:
                result.append(letters[letter])
                state_a = next_a
                state_b = next_b
                depth -= 1
                break
    return "".join(result)
```
