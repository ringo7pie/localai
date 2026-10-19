```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("bad alphabet")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pat = pattern
        self.pos = 0
        self.alpha = alphabet
        self.index = {ch: k for k, ch in enumerate(alphabet)}
        self.allset = frozenset(range(len(alphabet)))

    def parse(self):
        node = self.parse_alt()
        if self.pos != len(self.pat):
            raise ValueError("unbalanced )")
        return node

    def parse_alt(self):
        options = [self.parse_seq()]
        while self.pos < len(self.pat) and self.pat[self.pos] == '|':
            self.pos += 1
            options.append(self.parse_seq())
        if len(options) == 1:
            return options[0]
        return ('alt', options)

    def parse_seq(self):
        items = []
        pat = self.pat
        while self.pos < len(pat) and pat[self.pos] not in '|)':
            ch = pat[self.pos]
            if ch in '*+?':
                raise ValueError("nothing to repeat")
            atom = self.parse_atom()
            if self.pos < len(pat) and pat[self.pos] in '*+?':
                quant = pat[self.pos]
                self.pos += 1
                if self.pos < len(pat) and pat[self.pos] in '*+?':
                    raise ValueError("multiple repeat")
                atom = (quant, atom)
            items.append(atom)
        return ('cat', items)

    def char_set(self, ch):
        if ch in self.index:
            return frozenset([self.index[ch]])
        return frozenset()

    def parse_atom(self):
        pat = self.pat
        ch = pat[self.pos]
        if ch == '(':
            self.pos += 1
            node = self.parse_alt()
            if self.pos >= len(pat) or pat[self.pos] != ')':
                raise ValueError("unbalanced (")
            self.pos += 1
            return node
        if ch == '.':
            self.pos += 1
            return ('set', self.allset)
        if ch == '\\':
            if self.pos + 1 >= len(pat):
                raise ValueError("trailing backslash")
            self.pos += 2
            return ('set', self.char_set(pat[self.pos - 1]))
        if ch == '[':
            return self.parse_class()
        self.pos += 1
        return ('set', self.char_set(ch))

    def read_class_char(self):
        pat = self.pat
        if self.pos >= len(pat):
            raise ValueError("unclosed class")
        ch = pat[self.pos]
        if ch == '\\':
            if self.pos + 1 >= len(pat):
                raise ValueError("trailing backslash")
            self.pos += 2
            return pat[self.pos - 1]
        self.pos += 1
        return ch

    def parse_class(self):
        pat = self.pat
        self.pos += 1
        negate = False
        if self.pos < len(pat) and pat[self.pos] == '^':
            negate = True
            self.pos += 1
        members = set()
        count = 0
        while True:
            if self.pos >= len(pat):
                raise ValueError("unclosed class")
            if pat[self.pos] == ']':
                if count == 0:
                    raise ValueError("empty class")
                self.pos += 1
                break
            first = self.read_class_char()
            if (self.pos + 1 < len(pat) and pat[self.pos] == '-'
                    and pat[self.pos + 1] != ']'):
                self.pos += 1
                last = self.read_class_char()
                if ord(first) > ord(last):
                    raise ValueError("bad range")
                for k, letter in enumerate(self.alpha):
                    if ord(first) <= ord(letter) <= ord(last):
                        members.add(k)
            else:
                if first in self.index:
                    members.add(self.index[first])
            count += 1
        if negate:
            return ('set', frozenset(self.allset - members))
        return ('set', frozenset(members))


class _NFA:
    def __init__(self):
        self.eps = []
        self.trans = []

    def new(self):
        self.eps.append([])
        self.trans.append([])
        return len(self.eps) - 1

    def build(self, node):
        kind = node[0]
        if kind == 'set':
            start = self.new()
            end = self.new()
            if node[1]:
                self.trans[start].append((node[1], end))
            return start, end
        if kind == 'cat':
            start = self.new()
            cur = start
            for item in node[1]:
                sub_start, sub_end = self.build(item)
                self.eps[cur].append(sub_start)
                cur = sub_end
            return start, cur
        if kind == 'alt':
            start = self.new()
            end = self.new()
            for item in node[1]:
                sub_start, sub_end = self.build(item)
                self.eps[start].append(sub_start)
                self.eps[sub_end].append(end)
            return start, end
        sub_start, sub_end = self.build(node[1])
        start = self.new()
        end = self.new()
        self.eps[start].append(sub_start)
        self.eps[sub_end].append(end)
        if kind in '*?':
            self.eps[start].append(end)
        if kind in '*+':
            self.eps[sub_end].append(sub_start)
        return start, end


def _build_dfa(pattern, alphabet):
    _check_alphabet(alphabet)
    tree = _Parser(pattern, alphabet).parse()
    nfa = _NFA()
    nfa_start, nfa_end = nfa.build(tree)
    nletters = len(alphabet)

    def closure(states):
        stack = list(states)
        seen = set(states)
        while stack:
            st = stack.pop()
            for nxt in nfa.eps[st]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return frozenset(seen)

    start = closure([nfa_start])
    ids = {start: 0}
    order = [start]
    delta = []
    accept = []
    idx = 0
    while idx < len(order):
        cur = order[idx]
        idx += 1
        accept.append(nfa_end in cur)
        moves = [set() for _ in range(nletters)]
        for st in cur:
            for cset, target in nfa.trans[st]:
                for letter in cset:
                    moves[letter].add(target)
        row = []
        for letter in range(nletters):
            nxt = closure(moves[letter]) if moves[letter] else frozenset()
            if nxt not in ids:
                ids[nxt] = len(order)
                order.append(nxt)
            row.append(ids[nxt])
        delta.append(row)
    return delta, accept


def _minimize_count(delta, accept, nletters):
    count = len(delta)
    inverse = [[[] for _ in range(count)] for _ in range(nletters)]
    for st in range(count):
        for letter in range(nletters):
            inverse[letter][delta[st][letter]].append(st)
    finals = {st for st in range(count) if accept[st]}
    others = set(range(count)) - finals
    blocks = []
    block_of = [0] * count
    for group in (finals, others):
        if group:
            bid = len(blocks)
            blocks.append(set(group))
            for st in group:
                block_of[st] = bid
    work = set(range(len(blocks)))
    while work:
        splitter = work.pop()
        members = list(blocks[splitter])
        for letter in range(nletters):
            inv = inverse[letter]
            touched = {}
            for target in members:
                for src in inv[target]:
                    touched.setdefault(block_of[src], set()).add(src)
            for bid, subset in touched.items():
                if len(subset) < len(blocks[bid]):
                    new_id = len(blocks)
                    blocks[bid] -= subset
                    blocks.append(subset)
                    for st in subset:
                        block_of[st] = new_id
                    if bid in work:
                        work.add(new_id)
                    elif len(subset) <= len(blocks[bid]):
                        work.add(new_id)
                    else:
                        work.add(bid)
    return len(blocks)


def min_dfa_size(pattern: str, alphabet: str) -> int:
    delta, accept = _build_dfa(pattern, alphabet)
    return _minimize_count(delta, accept, len(alphabet))


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    delta1, accept1 = _build_dfa(p1, alphabet)
    delta2, accept2 = _build_dfa(p2, alphabet)
    start = (0, 0)
    parent = {start: None}
    queue = deque([start])
    found = None
    while queue:
        pair = queue.popleft()
        if accept1[pair[0]] != accept2[pair[1]]:
            found = pair
            break
        for letter in range(len(alphabet)):
            nxt = (delta1[pair[0]][letter], delta2[pair[1]][letter])
            if nxt not in parent:
                parent[nxt] = (pair, letter)
                queue.append(nxt)
    if found is None:
        return None
    chars = []
    cur = found
    while parent[cur] is not None:
        prev, letter = parent[cur]
        chars.append(alphabet[letter])
        cur = prev
    return ''.join(reversed(chars))
```
