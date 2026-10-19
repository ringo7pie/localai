```python
from collections import deque

_QUANT = "*+?"


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("empty alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate character in alphabet")
    return {ch: idx for idx, ch in enumerate(alphabet)}


class _Parser:
    def __init__(self, pattern, alphabet, alpha_index):
        self.pattern = pattern
        self.n = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.alpha_index = alpha_index
        self.all_set = frozenset(range(len(alphabet)))

    def parse(self):
        node = self.parse_alt()
        if self.pos != self.n:
            raise ValueError("unmatched ')'")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.pos < self.n and self.pattern[self.pos] == "|":
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_seq(self):
        items = []
        pattern = self.pattern
        while self.pos < self.n:
            ch = pattern[self.pos]
            if ch in "|)":
                break
            if ch in _QUANT:
                raise ValueError("nothing to repeat")
            atom = self.parse_atom()
            if self.pos < self.n and pattern[self.pos] in _QUANT:
                quant = pattern[self.pos]
                self.pos += 1
                if self.pos < self.n and pattern[self.pos] in _QUANT:
                    raise ValueError("multiple repeat")
                if quant == "*":
                    atom = ("star", atom)
                elif quant == "+":
                    atom = ("plus", atom)
                else:
                    atom = ("opt", atom)
            items.append(atom)
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def char_set(self, ch):
        idx = self.alpha_index.get(ch)
        if idx is None:
            return ("set", frozenset())
        return ("set", frozenset((idx,)))

    def parse_atom(self):
        pattern = self.pattern
        ch = pattern[self.pos]
        if ch == "(":
            self.pos += 1
            inner = self.parse_alt()
            if self.pos >= self.n or pattern[self.pos] != ")":
                raise ValueError("unmatched '('")
            self.pos += 1
            return inner
        if ch == ".":
            self.pos += 1
            return ("set", self.all_set)
        if ch == "\\":
            if self.pos + 1 >= self.n:
                raise ValueError("trailing backslash")
            lit = pattern[self.pos + 1]
            self.pos += 2
            return self.char_set(lit)
        if ch == "[":
            return self.parse_class()
        self.pos += 1
        return self.char_set(ch)

    def read_class_char(self):
        pattern = self.pattern
        if self.pos >= self.n:
            raise ValueError("unterminated character class")
        ch = pattern[self.pos]
        if ch == "\\":
            if self.pos + 1 >= self.n:
                raise ValueError("trailing backslash")
            self.pos += 2
            return pattern[self.pos - 1]
        self.pos += 1
        return ch

    def parse_class(self):
        pattern = self.pattern
        self.pos += 1
        negate = False
        if self.pos < self.n and pattern[self.pos] == "^":
            negate = True
            self.pos += 1
        chosen = set()
        count = 0
        while True:
            if self.pos >= self.n:
                raise ValueError("unterminated character class")
            ch = pattern[self.pos]
            if ch == "]":
                if count == 0:
                    raise ValueError("empty character class")
                self.pos += 1
                break
            first = self.read_class_char()
            if (self.pos + 1 < self.n and pattern[self.pos] == "-"
                    and pattern[self.pos + 1] != "]"):
                self.pos += 1
                last = self.read_class_char()
                if first > last:
                    raise ValueError("bad character range")
                for idx, al in enumerate(self.alphabet):
                    if first <= al <= last:
                        chosen.add(idx)
            else:
                idx = self.alpha_index.get(first)
                if idx is not None:
                    chosen.add(idx)
            count += 1
        if negate:
            return ("set", self.all_set - frozenset(chosen))
        return ("set", frozenset(chosen))


class _NFA:
    def __init__(self):
        self.eps = []
        self.edges = []

    def new_state(self):
        self.eps.append([])
        self.edges.append([])
        return len(self.eps) - 1

    def build(self, node):
        kind = node[0]
        if kind == "set":
            start = self.new_state()
            end = self.new_state()
            if node[1]:
                self.edges[start].append((node[1], end))
            return start, end
        if kind == "cat":
            items = node[1]
            if not items:
                start = self.new_state()
                end = self.new_state()
                self.eps[start].append(end)
                return start, end
            first_start, prev_end = self.build(items[0])
            for item in items[1:]:
                sub_start, sub_end = self.build(item)
                self.eps[prev_end].append(sub_start)
                prev_end = sub_end
            return first_start, prev_end
        if kind == "alt":
            start = self.new_state()
            end = self.new_state()
            for branch in node[1]:
                sub_start, sub_end = self.build(branch)
                self.eps[start].append(sub_start)
                self.eps[sub_end].append(end)
            return start, end
        sub_start, sub_end = self.build(node[1])
        start = self.new_state()
        end = self.new_state()
        self.eps[start].append(sub_start)
        self.eps[sub_end].append(end)
        if kind == "star":
            self.eps[start].append(end)
            self.eps[sub_end].append(sub_start)
        elif kind == "plus":
            self.eps[sub_end].append(sub_start)
        else:  # opt
            self.eps[start].append(end)
        return start, end


def _build_dfa(pattern, alphabet, alpha_index):
    tree = _Parser(pattern, alphabet, alpha_index).parse()
    nfa = _NFA()
    nfa_start, nfa_end = nfa.build(tree)
    num = len(nfa.eps)
    k = len(alphabet)

    closure = [0] * num
    for state in range(num):
        seen = {state}
        stack = [state]
        while stack:
            cur = stack.pop()
            for nxt in nfa.eps[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        mask = 0
        for member in seen:
            mask |= 1 << member
        closure[state] = mask

    trans_mask = [[0] * k for _ in range(num)]
    for state in range(num):
        row = trans_mask[state]
        for charset, target in nfa.edges[state]:
            tmask = closure[target]
            for cidx in charset:
                row[cidx] |= tmask

    end_bit = 1 << nfa_end
    start_mask = closure[nfa_start]
    ids = {start_mask: 0}
    masks = [start_mask]
    delta = []
    accepting = []
    head = 0
    while head < len(masks):
        mask = masks[head]
        head += 1
        accepting.append(bool(mask & end_bit))
        bits = []
        rest = mask
        while rest:
            low = rest & -rest
            bits.append(low.bit_length() - 1)
            rest ^= low
        row = []
        for cidx in range(k):
            result = 0
            for bit in bits:
                result |= trans_mask[bit][cidx]
            target = ids.get(result)
            if target is None:
                target = len(masks)
                ids[result] = target
                masks.append(result)
            row.append(target)
        delta.append(row)
    return delta, accepting


def _minimize(delta, accepting, k):
    n = len(delta)
    inv = [[[] for _ in range(n)] for _ in range(k)]
    for state in range(n):
        row = delta[state]
        for cidx in range(k):
            inv[cidx][row[cidx]].append(state)

    blocks = []
    block_of = [0] * n
    acc_group = [s for s in range(n) if accepting[s]]
    rej_group = [s for s in range(n) if not accepting[s]]
    for group in (acc_group, rej_group):
        if group:
            bidx = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = bidx

    in_work = set()
    work = []

    def push(pair):
        if pair not in in_work:
            in_work.add(pair)
            work.append(pair)

    for bidx in range(len(blocks)):
        for cidx in range(k):
            push((bidx, cidx))

    while work:
        pair = work.pop()
        in_work.discard(pair)
        bidx, cidx = pair
        inv_c = inv[cidx]
        pre = set()
        for target in blocks[bidx]:
            pre.update(inv_c[target])
        touched = {}
        for state in pre:
            touched.setdefault(block_of[state], []).append(state)
        for yidx, members in touched.items():
            if len(members) == len(blocks[yidx]):
                continue
            new_set = set(members)
            blocks[yidx] -= new_set
            new_idx = len(blocks)
            blocks.append(new_set)
            for state in members:
                block_of[state] = new_idx
            for didx in range(k):
                if (yidx, didx) in in_work:
                    push((new_idx, didx))
                elif len(new_set) <= len(blocks[yidx]):
                    push((new_idx, didx))
                else:
                    push((yidx, didx))

    num_blocks = len(blocks)
    new_delta = [None] * num_blocks
    new_acc = [False] * num_blocks
    for bidx, members in enumerate(blocks):
        rep = next(iter(members))
        new_delta[bidx] = [block_of[t] for t in delta[rep]]
        new_acc[bidx] = accepting[rep]
    return new_delta, new_acc, block_of[0]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    alpha_index = _check_alphabet(alphabet)
    delta, accepting = _build_dfa(pattern, alphabet, alpha_index)
    new_delta, _acc, _start = _minimize(delta, accepting, len(alphabet))
    return len(new_delta)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    alpha_index = _check_alphabet(alphabet)
    k = len(alphabet)
    d1, a1 = _build_dfa(p1, alphabet, alpha_index)
    d2, a2 = _build_dfa(p2, alphabet, alpha_index)
    d1, a1, s1 = _minimize(d1, a1, k)
    d2, a2, s2 = _minimize(d2, a2, k)

    start = (s1, s2)
    if a1[s1] != a2[s2]:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        row1 = d1[cur[0]]
        row2 = d2[cur[1]]
        for cidx in range(k):
            nxt = (row1[cidx], row2[cidx])
            if nxt in parent:
                continue
            parent[nxt] = (cur, cidx)
            if a1[nxt[0]] != a2[nxt[1]]:
                chars = []
                node = nxt
                while parent[node] is not None:
                    prev, ch_idx = parent[node]
                    chars.append(alphabet[ch_idx])
                    node = prev
                return "".join(reversed(chars))
            queue.append(nxt)
    return None
```
