```python
def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("alphabet must be a non-empty string")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet has duplicate characters")


def _iter_bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.index = {ch: i for i, ch in enumerate(alphabet)}
        self.full = (1 << len(alphabet)) - 1

    def parse(self):
        node = self._parse_alt()
        if self.pos != self.length:
            raise ValueError("unmatched ')'")
        return node

    def _parse_alt(self):
        branches = [self._parse_cat()]
        while self.pos < self.length and self.pattern[self.pos] == '|':
            self.pos += 1
            branches.append(self._parse_cat())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def _parse_cat(self):
        items = []
        while self.pos < self.length and self.pattern[self.pos] not in '|)':
            atom = self._parse_atom()
            if self.pos < self.length and self.pattern[self.pos] in '*+?':
                quant = self.pattern[self.pos]
                self.pos += 1
                if self.pos < self.length and self.pattern[self.pos] in '*+?':
                    raise ValueError("stacked quantifiers")
                if quant == '*':
                    atom = ('star', atom)
                elif quant == '+':
                    atom = ('plus', atom)
                else:
                    atom = ('opt', atom)
            items.append(atom)
        if not items:
            return ('eps',)
        if len(items) == 1:
            return items[0]
        return ('cat', items)

    def _char_mask(self, ch):
        idx = self.index.get(ch)
        if idx is None:
            return 0
        return 1 << idx

    def _parse_atom(self):
        ch = self.pattern[self.pos]
        if ch in '*+?':
            raise ValueError("quantifier without element")
        if ch == '(':
            self.pos += 1
            node = self._parse_alt()
            if self.pos >= self.length or self.pattern[self.pos] != ')':
                raise ValueError("unmatched '('")
            self.pos += 1
            return node
        if ch == '[':
            return self._parse_class()
        if ch == '.':
            self.pos += 1
            return ('set', self.full)
        if ch == '\\':
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            lit = self.pattern[self.pos + 1]
            self.pos += 2
            return ('set', self._char_mask(lit))
        self.pos += 1
        return ('set', self._char_mask(ch))

    def _read_class_char(self):
        ch = self.pattern[self.pos]
        if ch == '\\':
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash in class")
            lit = self.pattern[self.pos + 1]
            self.pos += 2
            return lit
        self.pos += 1
        return ch

    def _parse_class(self):
        self.pos += 1  # skip '['
        negate = False
        if self.pos < self.length and self.pattern[self.pos] == '^':
            negate = True
            self.pos += 1
        mask = 0
        count = 0
        while True:
            if self.pos >= self.length:
                raise ValueError("unclosed '['")
            if self.pattern[self.pos] == ']':
                self.pos += 1
                break
            low_ch = self._read_class_char()
            if (self.pos + 1 < self.length
                    and self.pattern[self.pos] == '-'
                    and self.pattern[self.pos + 1] != ']'):
                self.pos += 1
                high_ch = self._read_class_char()
                if ord(low_ch) > ord(high_ch):
                    raise ValueError("bad range in class")
                for i, letter in enumerate(self.alphabet):
                    if low_ch <= letter <= high_ch:
                        mask |= 1 << i
            else:
                mask |= self._char_mask(low_ch)
            count += 1
        if count == 0:
            raise ValueError("empty class")
        if negate:
            mask = self.full & ~mask
        return ('set', mask)


def _glushkov(node):
    pos_sets = [0]
    follow = [0]

    def rec(nd):
        kind = nd[0]
        if kind == 'eps':
            return True, 0, 0
        if kind == 'set':
            if nd[1] == 0:
                return False, 0, 0
            position = len(pos_sets)
            pos_sets.append(nd[1])
            follow.append(0)
            bit = 1 << position
            return False, bit, bit
        if kind == 'cat':
            nullable, first, last = True, 0, 0
            for child in nd[1]:
                c_null, c_first, c_last = rec(child)
                if c_first:
                    for p in _iter_bits(last):
                        follow[p] |= c_first
                if nullable:
                    first |= c_first
                if c_null:
                    last |= c_last
                else:
                    last = c_last
                nullable = nullable and c_null
            return nullable, first, last
        if kind == 'alt':
            nullable, first, last = False, 0, 0
            for child in nd[1]:
                c_null, c_first, c_last = rec(child)
                nullable = nullable or c_null
                first |= c_first
                last |= c_last
            return nullable, first, last
        if kind == 'star' or kind == 'plus':
            c_null, c_first, c_last = rec(nd[1])
            if c_first:
                for p in _iter_bits(c_last):
                    follow[p] |= c_first
            return (True if kind == 'star' else c_null), c_first, c_last
        if kind == 'opt':
            c_null, c_first, c_last = rec(nd[1])
            return True, c_first, c_last
        raise ValueError("internal error")

    nullable, first, last = rec(node)
    follow[0] = first
    accept_mask = last | (1 if nullable else 0)
    return pos_sets, follow, accept_mask


def _build_dfa(pattern, alphabet):
    k = len(alphabet)
    ast = _Parser(pattern, alphabet).parse()
    pos_sets, follow, accept_mask = _glushkov(ast)
    trans_pc = []
    for p in range(len(pos_sets)):
        row = [0] * k
        for q in _iter_bits(follow[p]):
            char_set = pos_sets[q]
            qbit = 1 << q
            for c in range(k):
                if (char_set >> c) & 1:
                    row[c] |= qbit
        trans_pc.append(row)
    ids = {1: 0}
    order = [1]
    trans = []
    accepting = []
    idx = 0
    while idx < len(order):
        mask = order[idx]
        idx += 1
        nxt = [0] * k
        for p in _iter_bits(mask):
            row = trans_pc[p]
            for c in range(k):
                nxt[c] |= row[c]
        row_ids = []
        for c in range(k):
            target = nxt[c]
            j = ids.get(target)
            if j is None:
                j = len(order)
                ids[target] = j
                order.append(target)
            row_ids.append(j)
        trans.append(row_ids)
        accepting.append(bool(mask & accept_mask))
    return trans, accepting


def _minimize(trans, accepting, k):
    n = len(trans)
    inv = [[[] for _ in range(n)] for _ in range(k)]
    for s in range(n):
        row = trans[s]
        for c in range(k):
            inv[c][row[c]].append(s)
    acc = [s for s in range(n) if accepting[s]]
    rej = [s for s in range(n) if not accepting[s]]
    blocks = []
    block_of = [0] * n
    for group in (acc, rej):
        if group:
            bid = len(blocks)
            blocks.append(set(group))
            for s in group:
                block_of[s] = bid
    work = set(range(len(blocks)))
    while work:
        a = work.pop()
        splitter = list(blocks[a])
        for c in range(k):
            inv_c = inv[c]
            hit = {}
            for t in splitter:
                for s in inv_c[t]:
                    b = block_of[s]
                    lst = hit.get(b)
                    if lst is None:
                        hit[b] = [s]
                    else:
                        lst.append(s)
            for b, members in hit.items():
                block = blocks[b]
                if len(members) == len(block):
                    continue
                inter = set(members)
                block -= inter
                nb = len(blocks)
                blocks.append(inter)
                for s in inter:
                    block_of[s] = nb
                if b in work or len(inter) <= len(block):
                    work.add(nb)
                else:
                    work.add(b)
    return len(blocks), block_of


def _min_dfa(pattern, alphabet):
    k = len(alphabet)
    trans, accepting = _build_dfa(pattern, alphabet)
    count, block_of = _minimize(trans, accepting, k)
    qtrans = [None] * count
    qacc = [False] * count
    for s in range(len(trans)):
        b = block_of[s]
        if qtrans[b] is None:
            qtrans[b] = [block_of[t] for t in trans[s]]
            qacc[b] = accepting[s]
    return block_of[0], qtrans, qacc


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    start, qtrans, qacc = _min_dfa(pattern, alphabet)
    return len(qtrans)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    start1, trans1, acc1 = _min_dfa(p1, alphabet)
    start2, trans2, acc2 = _min_dfa(p2, alphabet)
    k = len(alphabet)
    start = (start1, start2)
    parent = {start: None}
    queue = [start]
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        left, right = node
        if acc1[left] != acc2[right]:
            chars = []
            cur = node
            while parent[cur] is not None:
                prev, c = parent[cur]
                chars.append(alphabet[c])
                cur = prev
            chars.reverse()
            return ''.join(chars)
        row1 = trans1[left]
        row2 = trans2[right]
        for c in range(k):
            nxt = (row1[c], row2[c])
            if nxt not in parent:
                parent[nxt] = (node, c)
                queue.append(nxt)
    return None
```
