```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("alphabet must be non-empty")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet has duplicate characters")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alpha_set = frozenset(alphabet)

    def parse(self):
        node = self._alt()
        if self.pos < self.length:
            raise ValueError("unmatched ')'")
        return node

    def _alt(self):
        branches = [self._concat()]
        while self.pos < self.length and self.pattern[self.pos] == '|':
            self.pos += 1
            branches.append(self._concat())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def _concat(self):
        items = []
        quant_names = {'*': 'star', '+': 'plus', '?': 'opt'}
        while self.pos < self.length:
            char = self.pattern[self.pos]
            if char == '|' or char == ')':
                break
            if char in quant_names:
                raise ValueError("quantifier without target")
            atom = self._atom()
            if self.pos < self.length and self.pattern[self.pos] in quant_names:
                quant = self.pattern[self.pos]
                self.pos += 1
                atom = (quant_names[quant], atom)
            items.append(atom)
        return ('cat', items)

    def _atom(self):
        char = self.pattern[self.pos]
        if char == '(':
            self.pos += 1
            inner = self._alt()
            if self.pos >= self.length or self.pattern[self.pos] != ')':
                raise ValueError("unmatched '('")
            self.pos += 1
            return inner
        if char == '[':
            return self._char_class()
        if char == '\\':
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            literal = self.pattern[self.pos + 1]
            self.pos += 2
            return ('sym', frozenset([literal]) & self.alpha_set)
        if char == '.':
            self.pos += 1
            return ('sym', self.alpha_set)
        self.pos += 1
        return ('sym', frozenset([char]) & self.alpha_set)

    def _char_class(self):
        pattern = self.pattern
        length = self.length
        idx = self.pos + 1
        negate = False
        if idx < length and pattern[idx] == '^':
            negate = True
            idx += 1
        ranges = []
        while True:
            if idx >= length:
                raise ValueError("unclosed '['")
            char = pattern[idx]
            if char == ']':
                if not ranges:
                    raise ValueError("empty character class")
                idx += 1
                break
            if char == '\\':
                if idx + 1 >= length:
                    raise ValueError("trailing backslash in class")
                low = pattern[idx + 1]
                idx += 2
            else:
                low = char
                idx += 1
            if (idx < length and pattern[idx] == '-'
                    and idx + 1 < length and pattern[idx + 1] != ']'):
                if pattern[idx + 1] == '\\':
                    if idx + 2 >= length:
                        raise ValueError("trailing backslash in class")
                    high = pattern[idx + 2]
                    idx += 3
                else:
                    high = pattern[idx + 1]
                    idx += 2
                if low > high:
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                ranges.append((low, low))
        self.pos = idx
        matched = frozenset(
            ch for ch in self.alpha_set
            if any(lo <= ch <= hi for lo, hi in ranges)
        )
        if negate:
            matched = self.alpha_set - matched
        return ('sym', matched)


def _iter_bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _glushkov(root, alphabet):
    follow = [0]
    symsets = [frozenset()]

    def add_follow(last_mask, first_mask):
        if first_mask == 0:
            return
        for position in _iter_bits(last_mask):
            follow[position] |= first_mask

    def walk(node):
        kind = node[0]
        if kind == 'sym':
            position = len(follow)
            follow.append(0)
            symsets.append(node[1])
            bit = 1 << position
            return False, bit, bit
        if kind == 'cat':
            nullable, first, last = True, 0, 0
            for child in node[1]:
                c_null, c_first, c_last = walk(child)
                add_follow(last, c_first)
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
            for child in node[1]:
                c_null, c_first, c_last = walk(child)
                nullable = nullable or c_null
                first |= c_first
                last |= c_last
            return nullable, first, last
        c_null, c_first, c_last = walk(node[1])
        if kind == 'star':
            add_follow(c_last, c_first)
            return True, c_first, c_last
        if kind == 'plus':
            add_follow(c_last, c_first)
            return c_null, c_first, c_last
        # opt
        return True, c_first, c_last

    root_null, root_first, root_last = walk(root)
    follow[0] = root_first
    final_mask = root_last | (1 if root_null else 0)
    charmasks = []
    for symbol in alphabet:
        cmask = 0
        for position in range(1, len(symsets)):
            if symbol in symsets[position]:
                cmask |= 1 << position
        charmasks.append(cmask)
    return follow, final_mask, charmasks


def _build_dfa(pattern, alphabet):
    root = _Parser(pattern, alphabet).parse()
    follow, final_mask, charmasks = _glushkov(root, alphabet)
    ids = {1: 0}
    masks = [1]
    trans = []
    accept = []
    index = 0
    while index < len(masks):
        mask = masks[index]
        index += 1
        fol = 0
        for position in _iter_bits(mask):
            fol |= follow[position]
        row = []
        for cmask in charmasks:
            nxt = fol & cmask
            target = ids.get(nxt)
            if target is None:
                target = len(masks)
                ids[nxt] = target
                masks.append(nxt)
            row.append(target)
        trans.append(row)
        accept.append(bool(mask & final_mask))
    return trans, accept


def _minimize(trans, accept, num_chars):
    num_states = len(trans)
    inverse = [[[] for _ in range(num_states)] for _ in range(num_chars)]
    for state in range(num_states):
        row = trans[state]
        for char_idx in range(num_chars):
            inverse[char_idx][row[char_idx]].append(state)
    blocks = []
    block_of = [0] * num_states
    finals = [s for s in range(num_states) if accept[s]]
    nonfinals = [s for s in range(num_states) if not accept[s]]
    for group in (finals, nonfinals):
        if group:
            block_id = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = block_id
    work = list(range(len(blocks)))
    in_work = set(work)
    while work:
        splitter_id = work.pop()
        in_work.discard(splitter_id)
        splitter = list(blocks[splitter_id])
        for char_idx in range(num_chars):
            inv_c = inverse[char_idx]
            touched = {}
            for target in splitter:
                for state in inv_c[target]:
                    block_id = block_of[state]
                    members = touched.get(block_id)
                    if members is None:
                        touched[block_id] = [state]
                    else:
                        members.append(state)
            for block_id, members in touched.items():
                block = blocks[block_id]
                if len(members) < len(block):
                    new_block = set(members)
                    block -= new_block
                    new_id = len(blocks)
                    blocks.append(new_block)
                    for state in members:
                        block_of[state] = new_id
                    if block_id in in_work:
                        work.append(new_id)
                        in_work.add(new_id)
                    elif len(new_block) <= len(block):
                        work.append(new_id)
                        in_work.add(new_id)
                    else:
                        work.append(block_id)
                        in_work.add(block_id)
    min_trans = []
    min_accept = []
    for block in blocks:
        rep = next(iter(block))
        min_trans.append([block_of[t] for t in trans[rep]])
        min_accept.append(accept[rep])
    return min_trans, min_accept, block_of[0]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    trans, accept = _build_dfa(pattern, alphabet)
    min_trans, _, _ = _minimize(trans, accept, len(alphabet))
    return len(min_trans)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    trans1, accept1 = _build_dfa(p1, alphabet)
    trans2, accept2 = _build_dfa(p2, alphabet)
    num_chars = len(alphabet)
    m_trans1, m_accept1, start1 = _minimize(trans1, accept1, num_chars)
    m_trans2, m_accept2, start2 = _minimize(trans2, accept2, num_chars)
    start = (start1, start2)
    if m_accept1[start1] != m_accept2[start2]:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        row1 = m_trans1[pair[0]]
        row2 = m_trans2[pair[1]]
        for char_idx in range(num_chars):
            nxt = (row1[char_idx], row2[char_idx])
            if nxt in parent:
                continue
            parent[nxt] = (pair, char_idx)
            if m_accept1[nxt[0]] != m_accept2[nxt[1]]:
                chars = []
                node = nxt
                while parent[node] is not None:
                    prev, idx = parent[node]
                    chars.append(alphabet[idx])
                    node = prev
                return "".join(reversed(chars))
            queue.append(nxt)
    return None
```
