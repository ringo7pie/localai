```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("empty alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pat = pattern
        self.pos = 0
        self.length = len(pattern)
        self.alphabet = alphabet
        self.index = {ch: k for k, ch in enumerate(alphabet)}
        self.full = (1 << len(alphabet)) - 1
        self.cmasks = [0]  # position 0 is the initial state

    def _new_sym(self, mask):
        self.cmasks.append(mask)
        return ("sym", len(self.cmasks) - 1)

    def _char_mask(self, ch):
        k = self.index.get(ch)
        return 0 if k is None else (1 << k)

    def parse(self):
        node = self._alt()
        if self.pos < self.length:
            # only an unmatched ')' can stop the top-level parse early
            raise ValueError("unmatched ')'")
        return node

    def _alt(self):
        items = [self._cat()]
        while self.pos < self.length and self.pat[self.pos] == "|":
            self.pos += 1
            items.append(self._cat())
        if len(items) == 1:
            return items[0]
        return ("alt", items)

    def _cat(self):
        items = []
        while self.pos < self.length:
            ch = self.pat[self.pos]
            if ch == "|" or ch == ")":
                break
            if ch in "*+?":
                raise ValueError("quantifier without operand")
            atom = self._atom()
            if self.pos < self.length and self.pat[self.pos] in "*+?":
                quant = self.pat[self.pos]
                self.pos += 1
                if self.pos < self.length and self.pat[self.pos] in "*+?":
                    raise ValueError("stacked quantifiers")
                atom = (quant, atom)
            items.append(atom)
        return ("cat", items)

    def _atom(self):
        ch = self.pat[self.pos]
        if ch == "(":
            self.pos += 1
            node = self._alt()
            if self.pos >= self.length or self.pat[self.pos] != ")":
                raise ValueError("unmatched '('")
            self.pos += 1
            return node
        if ch == ".":
            self.pos += 1
            return self._new_sym(self.full)
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            lit = self.pat[self.pos + 1]
            self.pos += 2
            return self._new_sym(self._char_mask(lit))
        if ch == "[":
            return self._char_class()
        self.pos += 1
        return self._new_sym(self._char_mask(ch))

    def _read_class_char(self):
        if self.pos >= self.length:
            raise ValueError("unterminated character class")
        ch = self.pat[self.pos]
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("unterminated character class")
            lit = self.pat[self.pos + 1]
            self.pos += 2
            return lit
        self.pos += 1
        return ch

    def _char_class(self):
        self.pos += 1  # skip '['
        negate = False
        if self.pos < self.length and self.pat[self.pos] == "^":
            negate = True
            self.pos += 1
        mask = 0
        item_count = 0
        while True:
            if self.pos >= self.length:
                raise ValueError("unterminated character class")
            if self.pat[self.pos] == "]":
                self.pos += 1
                break
            low = self._read_class_char()
            if (self.pos + 1 < self.length
                    and self.pat[self.pos] == "-"
                    and self.pat[self.pos + 1] != "]"):
                self.pos += 1
                high = self._read_class_char()
                if low > high:
                    raise ValueError("bad range")
                for k, achar in enumerate(self.alphabet):
                    if low <= achar <= high:
                        mask |= 1 << k
            else:
                mask |= self._char_mask(low)
            item_count += 1
        if item_count == 0:
            raise ValueError("empty character class")
        if negate:
            mask = self.full & ~mask
        return self._new_sym(mask)


def _analyze(node, follow):
    """Return (nullable, first_mask, last_mask); fills follow."""
    kind = node[0]
    if kind == "sym":
        bit = 1 << node[1]
        return False, bit, bit
    if kind == "cat":
        nullable = True
        first = 0
        last = 0
        for item in node[1]:
            n_item, f_item, l_item = _analyze(item, follow)
            bits = last
            while bits:
                low = bits & -bits
                follow[low.bit_length() - 1] |= f_item
                bits ^= low
            if nullable:
                first |= f_item
            if n_item:
                last |= l_item
            else:
                last = l_item
            nullable = nullable and n_item
        return nullable, first, last
    if kind == "alt":
        nullable = False
        first = 0
        last = 0
        for item in node[1]:
            n_item, f_item, l_item = _analyze(item, follow)
            nullable = nullable or n_item
            first |= f_item
            last |= l_item
        return nullable, first, last
    # quantifiers
    n_sub, f_sub, l_sub = _analyze(node[1], follow)
    if kind == "*" or kind == "+":
        bits = l_sub
        while bits:
            low = bits & -bits
            follow[low.bit_length() - 1] |= f_sub
            bits ^= low
    if kind == "+":
        return n_sub, f_sub, l_sub
    return True, f_sub, l_sub


def _build_dfa(pattern, alphabet):
    parser = _Parser(pattern, alphabet)
    root = parser.parse()
    cmasks = parser.cmasks
    num_pos = len(cmasks)
    follow = [0] * num_pos
    nullable, first, last = _analyze(root, follow)
    follow[0] = first
    last_mask = last | (1 if nullable else 0)
    alpha_size = len(alphabet)

    fmask = []
    for p in range(num_pos):
        row = [0] * alpha_size
        bits = follow[p]
        while bits:
            low = bits & -bits
            q = low.bit_length() - 1
            bits ^= low
            cm = cmasks[q]
            for k in range(alpha_size):
                if (cm >> k) & 1:
                    row[k] |= low
        fmask.append(row)

    start = 1
    index = {start: 0}
    states = [start]
    delta = []
    i = 0
    while i < len(states):
        cur = states[i]
        nxt = [0] * alpha_size
        bits = cur
        while bits:
            low = bits & -bits
            p = low.bit_length() - 1
            bits ^= low
            frow = fmask[p]
            for k in range(alpha_size):
                nxt[k] |= frow[k]
        row = []
        for k in range(alpha_size):
            target = nxt[k]
            tid = index.get(target)
            if tid is None:
                tid = len(states)
                index[target] = tid
                states.append(target)
            row.append(tid)
        delta.append(row)
        i += 1
    accept = [bool(s & last_mask) for s in states]
    return delta, accept


def _minimize(delta, accept, alpha_size):
    num = len(delta)
    inv = [[[] for _ in range(num)] for _ in range(alpha_size)]
    for s in range(num):
        row = delta[s]
        for k in range(alpha_size):
            inv[k][row[k]].append(s)
    blocks = []
    block_of = [0] * num
    acc_states = [s for s in range(num) if accept[s]]
    rej_states = [s for s in range(num) if not accept[s]]
    for group in (acc_states, rej_states):
        if group:
            bid = len(blocks)
            blocks.append(set(group))
            for s in group:
                block_of[s] = bid
    work = list(range(len(blocks)))
    in_work = set(work)
    while work:
        splitter_id = work.pop()
        in_work.discard(splitter_id)
        splitter = list(blocks[splitter_id])
        for k in range(alpha_size):
            invk = inv[k]
            touched = {}
            for t in splitter:
                for s in invk[t]:
                    b = block_of[s]
                    lst = touched.get(b)
                    if lst is None:
                        touched[b] = [s]
                    else:
                        lst.append(s)
            for b, lst in touched.items():
                block = blocks[b]
                if len(lst) == len(block):
                    continue
                inter = set(lst)
                diff = block - inter
                if len(inter) <= len(diff):
                    small, large = inter, diff
                else:
                    small, large = diff, inter
                blocks[b] = large
                new_id = len(blocks)
                blocks.append(small)
                for s in small:
                    block_of[s] = new_id
                work.append(new_id)
                in_work.add(new_id)
    return blocks, block_of


def _min_dfa(pattern, alphabet):
    delta, accept = _build_dfa(pattern, alphabet)
    alpha_size = len(alphabet)
    blocks, block_of = _minimize(delta, accept, alpha_size)
    m_delta = []
    m_accept = []
    for blk in blocks:
        rep = next(iter(blk))
        m_delta.append([block_of[t] for t in delta[rep]])
        m_accept.append(accept[rep])
    return m_delta, m_accept, block_of[0]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    delta, accept = _build_dfa(pattern, alphabet)
    blocks, _ = _minimize(delta, accept, len(alphabet))
    return len(blocks)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    delta1, acc1, start1 = _min_dfa(p1, alphabet)
    delta2, acc2, start2 = _min_dfa(p2, alphabet)
    alpha_size = len(alphabet)
    n2 = len(delta2)
    start = start1 * n2 + start2
    parent = {start: None}
    queue = deque([start])
    while queue:
        code = queue.popleft()
        s1, s2 = divmod(code, n2)
        if acc1[s1] != acc2[s2]:
            chars = []
            cur = code
            while parent[cur] is not None:
                prev, k = parent[cur]
                chars.append(alphabet[k])
                cur = prev
            return "".join(reversed(chars))
        row1 = delta1[s1]
        row2 = delta2[s2]
        for k in range(alpha_size):
            nc = row1[k] * n2 + row2[k]
            if nc not in parent:
                parent[nc] = (code, k)
                queue.append(nc)
    return None
```
