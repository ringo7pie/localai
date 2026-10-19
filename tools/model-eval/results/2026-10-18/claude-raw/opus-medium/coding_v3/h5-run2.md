```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("empty alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.alpha_set = set(alphabet)
        self.alphabet = alphabet
        self.pos = 0

    def parse(self):
        node = self._alt()
        if self.pos != len(self.pattern):
            # only an unmatched ')' can stop the top-level parse early
            raise ValueError("unmatched ')'")
        return node

    def _peek(self):
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def _alt(self):
        branches = [self._concat()]
        while self._peek() == '|':
            self.pos += 1
            branches.append(self._concat())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def _concat(self):
        items = []
        while True:
            ch = self._peek()
            if ch is None or ch == '|' or ch == ')':
                break
            if ch in '*+?':
                raise ValueError("quantifier without operand")
            atom = self._atom()
            ch = self._peek()
            if ch is not None and ch in '*+?':
                self.pos += 1
                kind = {'*': 'star', '+': 'plus', '?': 'opt'}[ch]
                atom = (kind, atom)
                nxt = self._peek()
                if nxt is not None and nxt in '*+?':
                    raise ValueError("stacked quantifiers")
            items.append(atom)
        if not items:
            return ('eps',)
        if len(items) == 1:
            return items[0]
        return ('cat', items)

    def _literal(self, ch):
        if ch in self.alpha_set:
            return ('set', frozenset([ch]))
        return ('set', frozenset())

    def _atom(self):
        pattern = self.pattern
        ch = pattern[self.pos]
        if ch == '(':
            self.pos += 1
            inner = self._alt()
            if self._peek() != ')':
                raise ValueError("unmatched '('")
            self.pos += 1
            return inner
        if ch == '.':
            self.pos += 1
            return ('set', frozenset(self.alphabet))
        if ch == '\\':
            if self.pos + 1 >= len(pattern):
                raise ValueError("trailing backslash")
            lit = pattern[self.pos + 1]
            self.pos += 2
            return self._literal(lit)
        if ch == '[':
            return self._char_class()
        self.pos += 1
        return self._literal(ch)

    def _read_class_char(self):
        pattern = self.pattern
        if self.pos >= len(pattern):
            raise ValueError("unterminated character class")
        ch = pattern[self.pos]
        if ch == '\\':
            if self.pos + 1 >= len(pattern):
                raise ValueError("trailing backslash")
            lit = pattern[self.pos + 1]
            self.pos += 2
            return lit
        self.pos += 1
        return ch

    def _char_class(self):
        pattern = self.pattern
        self.pos += 1  # skip '['
        negate = False
        if self.pos < len(pattern) and pattern[self.pos] == '^':
            negate = True
            self.pos += 1
        chars = set()
        ranges = []
        count = 0
        while True:
            if self.pos >= len(pattern):
                raise ValueError("unterminated character class")
            if pattern[self.pos] == ']':
                self.pos += 1
                break
            first = self._read_class_char()
            if (self.pos + 1 < len(pattern)
                    and pattern[self.pos] == '-'
                    and pattern[self.pos + 1] != ']'):
                self.pos += 1
                last = self._read_class_char()
                if ord(first) > ord(last):
                    raise ValueError("bad range")
                ranges.append((ord(first), ord(last)))
            else:
                chars.add(first)
            count += 1
        if count == 0:
            raise ValueError("empty character class")
        matched = set()
        for letter in self.alphabet:
            code = ord(letter)
            hit = letter in chars
            if not hit:
                for low, high in ranges:
                    if low <= code <= high:
                        hit = True
                        break
            if hit:
                matched.add(letter)
        if negate:
            matched = set(self.alphabet) - matched
        return ('set', frozenset(matched))


class _NFA:
    def __init__(self):
        self.eps = []
        self.trans = []

    def new_state(self):
        self.eps.append([])
        self.trans.append([])
        return len(self.eps) - 1

    def build(self, node, index_of):
        kind = node[0]
        if kind == 'set':
            start = self.new_state()
            end = self.new_state()
            for ch in node[1]:
                self.trans[start].append((index_of[ch], end))
            return start, end
        if kind == 'eps':
            start = self.new_state()
            end = self.new_state()
            self.eps[start].append(end)
            return start, end
        if kind == 'cat':
            frags = [self.build(child, index_of) for child in node[1]]
            for idx in range(len(frags) - 1):
                self.eps[frags[idx][1]].append(frags[idx + 1][0])
            return frags[0][0], frags[-1][1]
        if kind == 'alt':
            start = self.new_state()
            end = self.new_state()
            for child in node[1]:
                fs, fe = self.build(child, index_of)
                self.eps[start].append(fs)
                self.eps[fe].append(end)
            return start, end
        fs, fe = self.build(node[1], index_of)
        start = self.new_state()
        end = self.new_state()
        if kind == 'star':
            self.eps[start].append(fs)
            self.eps[start].append(end)
            self.eps[fe].append(fs)
            self.eps[fe].append(end)
        elif kind == 'plus':
            self.eps[start].append(fs)
            self.eps[fe].append(fs)
            self.eps[fe].append(end)
        else:  # opt
            self.eps[start].append(fs)
            self.eps[start].append(end)
            self.eps[fe].append(end)
        return start, end


def _build_dfa(pattern, alphabet):
    """Return (delta, accepting) of the complete reachable DFA; start state is 0."""
    if not isinstance(pattern, str):
        raise ValueError("pattern must be a string")
    tree = _Parser(pattern, alphabet).parse()
    index_of = {ch: idx for idx, ch in enumerate(alphabet)}
    k = len(alphabet)
    nfa = _NFA()
    nfa_start, nfa_accept = nfa.build(tree, index_of)
    n = len(nfa.eps)

    closure = [0] * n
    for state in range(n):
        mask = 1 << state
        stack = [state]
        while stack:
            cur = stack.pop()
            for nxt in nfa.eps[cur]:
                bit = 1 << nxt
                if not mask & bit:
                    mask |= bit
                    stack.append(nxt)
        closure[state] = mask

    step = [None] * n
    important_mask = 0
    for state in range(n):
        if nfa.trans[state]:
            important_mask |= 1 << state
            row = [0] * k
            for cidx, target in nfa.trans[state]:
                row[cidx] |= closure[target]
            step[state] = row

    accept_bit = 1 << nfa_accept
    start_mask = closure[nfa_start]
    ids = {start_mask: 0}
    masks = [start_mask]
    delta = []
    accepting = []
    queue_index = 0
    while queue_index < len(masks):
        mask = masks[queue_index]
        queue_index += 1
        accepting.append(bool(mask & accept_bit))
        rest = mask & important_mask
        rows = []
        while rest:
            low = rest & -rest
            rows.append(step[low.bit_length() - 1])
            rest ^= low
        out = []
        for cidx in range(k):
            target = 0
            for row in rows:
                target |= row[cidx]
            tid = ids.get(target)
            if tid is None:
                tid = len(masks)
                ids[target] = tid
                masks.append(target)
            out.append(tid)
        delta.append(out)
    return delta, accepting


def _minimize_count(delta, accepting, k):
    n = len(delta)
    inverse = [[[] for _ in range(n)] for _ in range(k)]
    for state in range(n):
        row = delta[state]
        for cidx in range(k):
            inverse[cidx][row[cidx]].append(state)
    final_states = [s for s in range(n) if accepting[s]]
    other_states = [s for s in range(n) if not accepting[s]]
    blocks = []
    block_of = [0] * n
    for group in (final_states, other_states):
        if group:
            bid = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = bid
    worklist = list(range(len(blocks)))
    in_work = set(worklist)
    while worklist:
        splitter = worklist.pop()
        in_work.discard(splitter)
        members = list(blocks[splitter])
        for cidx in range(k):
            inv_c = inverse[cidx]
            touched = {}
            for target in members:
                for src in inv_c[target]:
                    bid = block_of[src]
                    lst = touched.get(bid)
                    if lst is None:
                        touched[bid] = [src]
                    else:
                        lst.append(src)
            for bid, lst in touched.items():
                if len(lst) < len(blocks[bid]):
                    new_block = set(lst)
                    blocks[bid] -= new_block
                    nid = len(blocks)
                    blocks.append(new_block)
                    for state in new_block:
                        block_of[state] = nid
                    if bid in in_work:
                        worklist.append(nid)
                        in_work.add(nid)
                    else:
                        smaller = nid if len(new_block) <= len(blocks[bid]) else bid
                        worklist.append(smaller)
                        in_work.add(smaller)
    return len(blocks)


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    delta, accepting = _build_dfa(pattern, alphabet)
    return _minimize_count(delta, accepting, len(alphabet))


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    delta1, acc1 = _build_dfa(p1, alphabet)
    delta2, acc2 = _build_dfa(p2, alphabet)
    k = len(alphabet)
    start = (0, 0)
    if acc1[0] != acc2[0]:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        s1, s2 = pair
        row1 = delta1[s1]
        row2 = delta2[s2]
        for cidx in range(k):
            nxt = (row1[cidx], row2[cidx])
            if nxt in parent:
                continue
            parent[nxt] = (pair, cidx)
            if acc1[nxt[0]] != acc2[nxt[1]]:
                chars = []
                cur = nxt
                while parent[cur] is not None:
                    prev, ci = parent[cur]
                    chars.append(alphabet[ci])
                    cur = prev
                return "".join(reversed(chars))
            queue.append(nxt)
    return None
```
