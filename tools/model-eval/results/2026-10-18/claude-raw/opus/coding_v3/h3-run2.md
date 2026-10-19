```python
_GENERIC = 1 << 62

_KEYWORDS = frozenset(('fun', 'let', 'rec', 'in', 'if', 'then', 'else', 'true', 'false'))
_LOWER = 'abcdefghijklmnopqrstuvwxyz'
_DIGIT_STR = '0123456789'
_NAME_START = frozenset(_LOWER + '_')
_NAME_CHARS = frozenset(_LOWER + _LOWER.upper() + _DIGIT_STR + "_'")
_DIGITS = frozenset(_DIGIT_STR)
_SPACES = frozenset(' \t\n\r')
_SINGLE = frozenset('(),+*=<')
_BINOPS = {
    '=': (1, False),
    '<': (1, False),
    '::': (2, True),
    '+': (3, False),
    '-': (3, False),
    '*': (4, False),
}

_INT = 'int'
_BOOL = 'bool'

_LIT_INT = ('int',)
_LIT_BOOL = ('bool',)
_LIT_NIL = ('nil',)


class _TVar:
    __slots__ = ('ref', 'level')

    def __init__(self, level):
        self.ref = None
        self.level = level


def _prune(t):
    if type(t) is not _TVar or t.ref is None:
        return t
    root = t.ref
    while type(root) is _TVar and root.ref is not None:
        root = root.ref
    while t is not root:
        nxt = t.ref
        t.ref = root
        t = nxt
    return root


def _run(gen):
    """Drive generator-based 'recursion' with an explicit stack."""
    stack = [gen]
    value = None
    while True:
        try:
            sub = stack[-1].send(value)
        except StopIteration as stop:
            stack.pop()
            value = stop.value
            if not stack:
                return value
            continue
        stack.append(sub)
        value = None


def _tokenize(src):
    kinds = []
    vals = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in _SPACES:
            i += 1
            continue
        if c in _DIGITS:
            j = i + 1
            while j < n and src[j] in _DIGITS:
                j += 1
            kinds.append('int')
            vals.append(src[i:j])
            i = j
            continue
        if c in _NAME_START:
            j = i + 1
            while j < n and src[j] in _NAME_CHARS:
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                kinds.append(word)
            else:
                kinds.append('name')
            vals.append(word)
            i = j
            continue
        if c == '-':
            if i + 1 < n and src[i + 1] == '>':
                kinds.append('->')
                vals.append('->')
                i += 2
            else:
                kinds.append('-')
                vals.append('-')
                i += 1
            continue
        if c == ':':
            if i + 1 < n and src[i + 1] == ':':
                kinds.append('::')
                vals.append('::')
                i += 2
                continue
            raise SyntaxError("unexpected ':'")
        if c == '[':
            if i + 1 < n and src[i + 1] == ']':
                kinds.append('nil')
                vals.append('[]')
                i += 2
                continue
            raise SyntaxError("'[' must be followed by ']'")
        if c in _SINGLE:
            kinds.append(c)
            vals.append(c)
            i += 1
            continue
        raise SyntaxError("unexpected character %r" % c)
    kinds.append('eof')
    vals.append(None)
    return kinds, vals


def _mkfun(params, body):
    for param in reversed(params):
        body = ('fun', param, body)
    return body


class _Parser:
    def __init__(self, kinds, vals):
        self.kinds = kinds
        self.vals = vals
        self.pos = 0

    def _expect(self, kind):
        if self.kinds[self.pos] != kind:
            raise SyntaxError("expected %s" % kind)
        self.pos += 1

    def _name(self):
        if self.kinds[self.pos] != 'name':
            raise SyntaxError("expected a name")
        value = self.vals[self.pos]
        self.pos += 1
        return value

    def _names(self):
        out = []
        kinds = self.kinds
        while kinds[self.pos] == 'name':
            out.append(self.vals[self.pos])
            self.pos += 1
        return out

    def expr(self):
        kinds = self.kinds
        k = kinds[self.pos]
        if k == 'fun':
            self.pos += 1
            params = self._names()
            if not params:
                raise SyntaxError("fun needs at least one parameter")
            self._expect('->')
            body = yield self.expr()
            return _mkfun(params, body)
        if k == 'let':
            self.pos += 1
            is_rec = False
            if kinds[self.pos] == 'rec':
                is_rec = True
                self.pos += 1
            name = self._name()
            params = self._names()
            if is_rec and not params:
                raise SyntaxError("let rec needs at least one parameter")
            self._expect('=')
            rhs = yield self.expr()
            self._expect('in')
            body = yield self.expr()
            if params:
                rhs = _mkfun(params, rhs)
            return ('letrec' if is_rec else 'let', name, rhs, body)
        if k == 'if':
            self.pos += 1
            cond = yield self.binary()
            self._expect('then')
            then_branch = yield self.expr()
            self._expect('else')
            else_branch = yield self.expr()
            return ('if', cond, then_branch, else_branch)
        return (yield self.binary())

    def binary(self):
        kinds = self.kinds
        first = yield self.app()
        out = [first]
        ops = []
        while True:
            k = kinds[self.pos]
            info = _BINOPS.get(k)
            if info is None:
                break
            self.pos += 1
            prec, right = info
            while ops:
                top_prec = _BINOPS[ops[-1]][0]
                if top_prec > prec or (top_prec == prec and not right):
                    op = ops.pop()
                    rhs = out.pop()
                    lhs = out.pop()
                    out.append(('bin', op, lhs, rhs))
                else:
                    break
            ops.append(k)
            operand = yield self.app()
            out.append(operand)
        while ops:
            op = ops.pop()
            rhs = out.pop()
            lhs = out.pop()
            out.append(('bin', op, lhs, rhs))
        return out[0]

    def app(self):
        kinds = self.kinds
        func = None
        while True:
            k = kinds[self.pos]
            if k == 'name':
                arg = ('var', self.vals[self.pos])
                self.pos += 1
            elif k == 'int':
                arg = _LIT_INT
                self.pos += 1
            elif k == 'true' or k == 'false':
                arg = _LIT_BOOL
                self.pos += 1
            elif k == 'nil':
                arg = _LIT_NIL
                self.pos += 1
            elif k == '(':
                self.pos += 1
                first = yield self.expr()
                if kinds[self.pos] == ',':
                    self.pos += 1
                    second = yield self.expr()
                    self._expect(')')
                    arg = ('tuple', first, second)
                else:
                    self._expect(')')
                    arg = first
            else:
                if func is None:
                    raise SyntaxError("unexpected token %s" % k)
                return func
            func = arg if func is None else ('app', func, arg)


def _bind(var, t):
    if type(t) is _TVar:
        if t.level > var.level:
            t.level = var.level
        var.ref = t
        return
    if type(t) is not str:
        lvl = var.level
        stack = [t]
        seen = set()
        while stack:
            node = _prune(stack.pop())
            if type(node) is _TVar:
                if node is var:
                    raise TypeError("recursive type")
                if node.level > lvl:
                    node.level = lvl
            elif type(node) is tuple:
                key = id(node)
                if key in seen:
                    continue
                seen.add(key)
                stack.extend(node[1:])
    var.ref = t


def _unify(a, b):
    work = [(a, b)]
    while work:
        x, y = work.pop()
        x = _prune(x)
        y = _prune(y)
        if x is y:
            continue
        if type(x) is _TVar:
            _bind(x, y)
        elif type(y) is _TVar:
            _bind(y, x)
        elif type(x) is str or type(y) is str:
            if not (type(x) is str and type(y) is str and x == y):
                raise TypeError("type mismatch")
        else:
            if x[0] != y[0]:
                raise TypeError("type mismatch")
            if x[0] == 'list':
                work.append((x[1], y[1]))
            else:
                work.append((x[2], y[2]))
                work.append((x[1], y[1]))


def _generalize(t, level):
    found = False
    stack = [t]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if type(node) is _TVar:
            if node.level > level and node.level != _GENERIC:
                node.level = _GENERIC
                found = True
            elif node.level == _GENERIC:
                found = True
        elif type(node) is tuple:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node[1:])
    return found


class _Infer:
    def __init__(self):
        self.level = 0
        self.env = {}
        a, b = _TVar(_GENERIC), _TVar(_GENERIC)
        self.env['fst'] = [(('->', ('*', a, b), a), True)]
        a, b = _TVar(_GENERIC), _TVar(_GENERIC)
        self.env['snd'] = [(('->', ('*', a, b), b), True)]
        a = _TVar(_GENERIC)
        self.env['hd'] = [(('->', ('list', a), a), True)]
        a = _TVar(_GENERIC)
        self.env['tl'] = [(('->', ('list', a), ('list', a)), True)]
        a = _TVar(_GENERIC)
        self.env['null'] = [(('->', ('list', a), _BOOL), True)]

    def _push(self, name, t, poly):
        stack = self.env.get(name)
        if stack is None:
            self.env[name] = [(t, poly)]
        else:
            stack.append((t, poly))

    def _pop(self, name):
        self.env[name].pop()

    def _instantiate(self, t):
        level = self.level
        root = _prune(t)
        memo = {}
        stack = [root]
        while stack:
            node = stack[-1]
            key = id(node)
            if key in memo:
                stack.pop()
                continue
            if type(node) is _TVar:
                memo[key] = _TVar(level) if node.level == _GENERIC else node
                stack.pop()
                continue
            if type(node) is str:
                memo[key] = node
                stack.pop()
                continue
            kids = [_prune(child) for child in node[1:]]
            missing = [child for child in kids if id(child) not in memo]
            if missing:
                stack.extend(missing)
                continue
            memo[key] = (node[0],) + tuple(memo[id(child)] for child in kids)
            stack.pop()
        return memo[id(root)]

    def walk(self, node):
        kind = node[0]
        if kind == 'var':
            name = node[1]
            stack = self.env.get(name)
            if not stack:
                raise NameError("name %r is not defined" % name)
            t, poly = stack[-1]
            return self._instantiate(t) if poly else t
        if kind == 'int':
            return _INT
        if kind == 'bool':
            return _BOOL
        if kind == 'nil':
            return ('list', _TVar(self.level))
        if kind == 'app':
            func_t = yield self.walk(node[1])
            arg_t = yield self.walk(node[2])
            result = _TVar(self.level)
            _unify(func_t, ('->', arg_t, result))
            return result
        if kind == 'tuple':
            first_t = yield self.walk(node[1])
            second_t = yield self.walk(node[2])
            return ('*', first_t, second_t)
        if kind == 'bin':
            op = node[1]
            left_t = yield self.walk(node[2])
            if op == '=':
                right_t = yield self.walk(node[3])
                _unify(left_t, right_t)
                return _BOOL
            if op == '::':
                right_t = yield self.walk(node[3])
                list_t = ('list', left_t)
                _unify(right_t, list_t)
                return list_t
            _unify(left_t, _INT)
            right_t = yield self.walk(node[3])
            _unify(right_t, _INT)
            return _BOOL if op == '<' else _INT
        if kind == 'if':
            cond_t = yield self.walk(node[1])
            _unify(cond_t, _BOOL)
            then_t = yield self.walk(node[2])
            else_t = yield self.walk(node[3])
            _unify(then_t, else_t)
            return then_t
        if kind == 'fun':
            param = node[1]
            param_t = _TVar(self.level)
            self._push(param, param_t, False)
            body_t = yield self.walk(node[2])
            self._pop(param)
            return ('->', param_t, body_t)
        if kind == 'let' or kind == 'letrec':
            name = node[1]
            if kind == 'let':
                self.level += 1
                bound_t = yield self.walk(node[2])
                self.level -= 1
            else:
                self.level += 1
                self_t = _TVar(self.level)
                self._push(name, self_t, False)
                rhs_t = yield self.walk(node[2])
                self._pop(name)
                _unify(self_t, rhs_t)
                self.level -= 1
                bound_t = self_t
            poly = _generalize(bound_t, self.level)
            self._push(name, bound_t, poly)
            body_t = yield self.walk(node[3])
            self._pop(name)
            return body_t
        raise SyntaxError("unknown node")


def _varname(index):
    letter = _LOWER[index % 26]
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix else '')


def _push_wrapped(stack, t, tags):
    pruned = _prune(t)
    if type(pruned) is tuple and pruned[0] in tags:
        stack.append((0, ')'))
        stack.append((1, pruned))
        stack.append((0, '('))
    else:
        stack.append((1, pruned))


def _show(t):
    names = {}
    out = []
    stack = [(1, t)]
    arrow_only = ('->',)
    arrow_or_tuple = ('->', '*')
    while stack:
        tag, item = stack.pop()
        if tag == 0:
            out.append(item)
            continue
        node = _prune(item)
        if type(node) is _TVar:
            key = id(node)
            index = names.get(key)
            if index is None:
                index = len(names)
                names[key] = index
            out.append(_varname(index))
        elif type(node) is str:
            out.append(node)
        else:
            head = node[0]
            if head == '->':
                stack.append((1, node[2]))
                stack.append((0, ' -> '))
                _push_wrapped(stack, node[1], arrow_only)
            elif head == '*':
                _push_wrapped(stack, node[2], arrow_or_tuple)
                stack.append((0, ' * '))
                _push_wrapped(stack, node[1], arrow_or_tuple)
            else:
                stack.append((0, ' list'))
                _push_wrapped(stack, node[1], arrow_or_tuple)
    return ''.join(out)


def infer(src: str) -> str:
    kinds, vals = _tokenize(src)
    parser = _Parser(kinds, vals)
    tree = _run(parser.expr())
    if kinds[parser.pos] != 'eof':
        raise SyntaxError("unexpected token %s" % kinds[parser.pos])
    checker = _Infer()
    result = _run(checker.walk(tree))
    return _show(result)
```
