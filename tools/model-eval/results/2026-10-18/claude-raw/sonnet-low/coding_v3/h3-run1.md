```python
import sys
import threading

_KEYWORDS = {'fun', 'let', 'rec', 'in', 'if', 'then', 'else', 'true', 'false'}
_GENERIC = 10 ** 9


def _lex(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in ' \t\n':
            i += 1
        elif '0' <= c <= '9':
            j = i
            while j < n and '0' <= src[j] <= '9':
                j += 1
            toks.append(('int', src[i:j]))
            i = j
        elif c == '_' or 'a' <= c <= 'z':
            j = i + 1
            while j < n and (src[j] == '_' or src[j] == "'" or 'a' <= src[j] <= 'z'
                             or 'A' <= src[j] <= 'Z' or '0' <= src[j] <= '9'):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append((word, None))
            else:
                toks.append(('name', word))
            i = j
        elif src.startswith('->', i):
            toks.append(('->', None))
            i += 2
        elif src.startswith('::', i):
            toks.append(('::', None))
            i += 2
        elif c in '(),+-*=<':
            toks.append((c, None))
            i += 1
        elif c == '[':
            j = i + 1
            while j < n and src[j] in ' \t\n':
                j += 1
            if j < n and src[j] == ']':
                toks.append(('nil', None))
                i = j + 1
            else:
                raise SyntaxError('bad [')
        else:
            raise SyntaxError('bad char')
    toks.append(('eof', None))
    return toks


_ATOM_START = ('int', 'name', 'true', 'false', '(', 'nil')


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos][0]

    def take(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        if self.peek() != kind:
            raise SyntaxError('expected ' + kind)
        self.pos += 1

    def ident(self):
        if self.peek() != 'name':
            raise SyntaxError('expected name')
        return self.take()[1]

    def params(self):
        names = []
        while self.peek() == 'name':
            names.append(self.take()[1])
        return names

    def expr(self):
        kind = self.peek()
        if kind == 'fun':
            self.take()
            names = self.params()
            if not names:
                raise SyntaxError('no params')
            self.expect('->')
            body = self.expr()
            for name in reversed(names):
                body = ('fun', name, body)
            return body
        if kind == 'let':
            self.take()
            is_rec = False
            if self.peek() == 'rec':
                self.take()
                is_rec = True
            name = self.ident()
            names = self.params()
            if is_rec and not names:
                raise SyntaxError('rec needs params')
            self.expect('=')
            bound = self.expr()
            self.expect('in')
            body = self.expr()
            for pname in reversed(names):
                bound = ('fun', pname, bound)
            if is_rec:
                return ('letrec', name, bound, body)
            return ('let', name, bound, body)
        if kind == 'if':
            self.take()
            cond = self.expr()
            self.expect('then')
            then_branch = self.expr()
            self.expect('else')
            else_branch = self.expr()
            return ('if', cond, then_branch, else_branch)
        return self.cmp()

    def cmp(self):
        left = self.cons()
        while self.peek() in ('=', '<'):
            op = self.take()[0]
            right = self.cons()
            left = ('bin', op, left, right)
        return left

    def cons(self):
        left = self.add()
        if self.peek() == '::':
            self.take()
            right = self.cons()
            return ('bin', '::', left, right)
        return left

    def add(self):
        left = self.mul()
        while self.peek() in ('+', '-'):
            op = self.take()[0]
            right = self.mul()
            left = ('bin', op, left, right)
        return left

    def mul(self):
        left = self.app()
        while self.peek() == '*':
            self.take()
            right = self.app()
            left = ('bin', '*', left, right)
        return left

    def app(self):
        func = self.atom()
        while self.peek() in _ATOM_START:
            func = ('app', func, self.atom())
        return func

    def atom(self):
        kind = self.peek()
        if kind == 'int':
            self.take()
            return ('int',)
        if kind == 'true' or kind == 'false':
            self.take()
            return ('bool',)
        if kind == 'name':
            return ('var', self.take()[1])
        if kind == 'nil':
            self.take()
            return ('nil',)
        if kind == '(':
            self.take()
            first = self.expr()
            if self.peek() == ',':
                self.take()
                second = self.expr()
                self.expect(')')
                return ('tuple', first, second)
            self.expect(')')
            return first
        raise SyntaxError('unexpected token')


class _TV:
    __slots__ = ('ref', 'level')

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TC:
    __slots__ = ('name', 'args')

    def __init__(self, name, args=()):
        self.name = name
        self.args = args


_INT = _TC('int')
_BOOL = _TC('bool')


def _prune(typ):
    if type(typ) is _TV and typ.ref is not None:
        root = typ
        while type(root) is _TV and root.ref is not None:
            root = root.ref
        cur = typ
        while type(cur) is _TV and cur.ref is not None:
            nxt = cur.ref
            cur.ref = root
            cur = nxt
        return root
    return typ


def _occurs_adjust(var, typ):
    typ = _prune(typ)
    if type(typ) is _TV:
        if typ is var:
            raise TypeError('occurs check')
        if typ.level > var.level:
            typ.level = var.level
    else:
        for arg in typ.args:
            _occurs_adjust(var, arg)


def _unify(left, right):
    left = _prune(left)
    right = _prune(right)
    if left is right:
        return
    if type(left) is _TV:
        _occurs_adjust(left, right)
        left.ref = right
    elif type(right) is _TV:
        _occurs_adjust(right, left)
        right.ref = left
    else:
        if left.name != right.name or len(left.args) != len(right.args):
            raise TypeError('mismatch')
        for a, b in zip(left.args, right.args):
            _unify(a, b)


def _generalize(typ, level):
    typ = _prune(typ)
    if type(typ) is _TV:
        if typ.level > level:
            typ.level = _GENERIC
    else:
        for arg in typ.args:
            _generalize(arg, level)


def _instantiate(typ, mapping, level):
    typ = _prune(typ)
    if type(typ) is _TV:
        if typ.level == _GENERIC:
            if typ not in mapping:
                mapping[typ] = _TV(level)
            return mapping[typ]
        return typ
    if not typ.args:
        return typ
    new_args = tuple(_instantiate(arg, mapping, level) for arg in typ.args)
    if all(a is b for a, b in zip(new_args, typ.args)):
        return typ
    return _TC(typ.name, new_args)


def _fn(arg, res):
    return _TC('->', (arg, res))


def _builtins():
    env = {}
    a = _TV(_GENERIC)
    b = _TV(_GENERIC)
    env['fst'] = _fn(_TC('*', (a, b)), a)
    env['snd'] = _fn(_TC('*', (a, b)), b)
    env['hd'] = _fn(_TC('list', (a,)), a)
    env['tl'] = _fn(_TC('list', (a,)), _TC('list', (a,)))
    env['null'] = _fn(_TC('list', (a,)), _BOOL)
    return env


_MISSING = object()


def _infer_node(node, level, env):
    kind = node[0]
    if kind == 'int':
        return _INT
    if kind == 'bool':
        return _BOOL
    if kind == 'nil':
        return _TC('list', (_TV(level),))
    if kind == 'var':
        name = node[1]
        if name not in env:
            raise NameError(name)
        return _instantiate(env[name], {}, level)
    if kind == 'tuple':
        first = _infer_node(node[1], level, env)
        second = _infer_node(node[2], level, env)
        return _TC('*', (first, second))
    if kind == 'fun':
        name = node[1]
        param = _TV(level)
        old = env.get(name, _MISSING)
        env[name] = param
        body = _infer_node(node[2], level, env)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return _fn(param, body)
    if kind == 'app':
        func_type = _infer_node(node[1], level, env)
        arg_type = _infer_node(node[2], level, env)
        result = _TV(level)
        _unify(func_type, _fn(arg_type, result))
        return result
    if kind == 'if':
        cond = _infer_node(node[1], level, env)
        _unify(cond, _BOOL)
        then_type = _infer_node(node[2], level, env)
        else_type = _infer_node(node[3], level, env)
        _unify(then_type, else_type)
        return then_type
    if kind == 'bin':
        op = node[1]
        left = _infer_node(node[2], level, env)
        right = _infer_node(node[3], level, env)
        if op in ('+', '-', '*'):
            _unify(left, _INT)
            _unify(right, _INT)
            return _INT
        if op == '<':
            _unify(left, _INT)
            _unify(right, _INT)
            return _BOOL
        if op == '=':
            _unify(left, right)
            return _BOOL
        _unify(right, _TC('list', (left,)))
        return right
    if kind == 'let':
        name = node[1]
        bound = _infer_node(node[2], level + 1, env)
        _generalize(bound, level)
        old = env.get(name, _MISSING)
        env[name] = bound
        result = _infer_node(node[3], level, env)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return result
    if kind == 'letrec':
        name = node[1]
        old = env.get(name, _MISSING)
        self_var = _TV(level + 1)
        env[name] = self_var
        bound = _infer_node(node[2], level + 1, env)
        _unify(self_var, bound)
        _generalize(self_var, level)
        result = _infer_node(node[3], level, env)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return result
    raise SyntaxError('unknown node')


def _var_name(index):
    letter = chr(ord('a') + index % 26)
    if index >= 26:
        return "'" + letter + str(index // 26)
    return "'" + letter


def _show(typ, ctx, names):
    typ = _prune(typ)
    if type(typ) is _TV:
        if typ not in names:
            names[typ] = _var_name(len(names))
        return names[typ]
    if typ.name == 'int' or typ.name == 'bool':
        return typ.name
    if typ.name == 'list':
        return _show(typ.args[0], 3, names) + ' list'
    if typ.name == '*':
        left = _show(typ.args[0], 2, names)
        right = _show(typ.args[1], 2, names)
        text = left + ' * ' + right
        return '(' + text + ')' if ctx >= 2 else text
    left = _show(typ.args[0], 1, names)
    right = _show(typ.args[1], 0, names)
    text = left + ' -> ' + right
    return '(' + text + ')' if ctx >= 1 else text


def _infer_impl(src):
    toks = _lex(src)
    parser = _Parser(toks)
    tree = parser.expr()
    if parser.peek() != 'eof':
        raise SyntaxError('trailing tokens')
    env = _builtins()
    typ = _infer_node(tree, 0, env)
    return _show(typ, 0, {})


def infer(src: str) -> str:
    box = {}

    def runner():
        try:
            box['value'] = _infer_impl(src)
        except BaseException as exc:
            box['error'] = exc

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000000)
    try:
        try:
            threading.stack_size(256 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()
    finally:
        sys.setrecursionlimit(old_limit)
        try:
            threading.stack_size(0)
        except (ValueError, RuntimeError):
            pass
    if 'error' in box:
        raise box['error']
    return box['value']
```
