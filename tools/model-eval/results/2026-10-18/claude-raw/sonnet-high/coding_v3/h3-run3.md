```python
import sys
import threading

_KEYWORDS = {'fun', 'let', 'rec', 'in', 'if', 'then', 'else', 'true', 'false'}
_ATOM_START = {'int', 'id', 'true', 'false', '[', '('}
_GENERIC = 10 ** 9


def _tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in ' \t\n\r':
            i += 1
            continue
        if '0' <= ch <= '9':
            j = i + 1
            while j < n and '0' <= src[j] <= '9':
                j += 1
            tokens.append(('int', src[i:j]))
            i = j
            continue
        if ch == '_' or 'a' <= ch <= 'z':
            j = i + 1
            while j < n:
                c2 = src[j]
                if c2 == '_' or c2 == "'" or 'a' <= c2 <= 'z' or 'A' <= c2 <= 'Z' or '0' <= c2 <= '9':
                    j += 1
                else:
                    break
            word = src[i:j]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(('id', word))
            i = j
            continue
        two = src[i:i + 2]
        if two == '->' or two == '::':
            tokens.append((two, two))
            i += 2
            continue
        if ch in '()+,-*=<[]':
            tokens.append((ch, ch))
            i += 1
            continue
        raise SyntaxError('unexpected character %r' % ch)
    tokens.append(('eof', ''))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self):
        return self.toks[self.pos][0]

    def advance(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        if self.peek() != kind:
            raise SyntaxError('expected %s' % kind)
        return self.advance()

    def parse_params(self):
        params = []
        while self.peek() == 'id':
            params.append(self.advance()[1])
        return params

    @staticmethod
    def wrap(params, body):
        for name in reversed(params):
            body = ('lam', name, body)
        return body

    def parse_expr(self):
        kind = self.peek()
        if kind == 'fun':
            self.advance()
            params = self.parse_params()
            if not params:
                raise SyntaxError('fun needs parameters')
            self.expect('->')
            body = self.parse_expr()
            return self.wrap(params, body)
        if kind == 'let':
            self.advance()
            is_rec = False
            if self.peek() == 'rec':
                self.advance()
                is_rec = True
            name = self.expect('id')[1]
            params = self.parse_params()
            if is_rec and not params:
                raise SyntaxError('let rec needs parameters')
            self.expect('=')
            bound = self.parse_expr()
            self.expect('in')
            body = self.parse_expr()
            bound = self.wrap(params, bound)
            return ('letrec' if is_rec else 'let', name, bound, body)
        if kind == 'if':
            self.advance()
            cond = self.parse_expr()
            self.expect('then')
            then_branch = self.parse_expr()
            self.expect('else')
            else_branch = self.parse_expr()
            return ('if', cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.peek() in ('=', '<'):
            op = self.advance()[0]
            right = self.parse_cons()
            left = ('bin', op, left, right)
        return left

    def parse_cons(self):
        operands = [self.parse_add()]
        while self.peek() == '::':
            self.advance()
            operands.append(self.parse_add())
        result = operands[-1]
        for index in range(len(operands) - 2, -1, -1):
            result = ('cons', operands[index], result)
        return result

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() in ('+', '-'):
            op = self.advance()[0]
            right = self.parse_mul()
            left = ('bin', op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.peek() == '*':
            self.advance()
            right = self.parse_app()
            left = ('bin', '*', left, right)
        return left

    def parse_app(self):
        left = self.parse_atom()
        while self.peek() in _ATOM_START:
            arg = self.parse_atom()
            left = ('app', left, arg)
        return left

    def parse_atom(self):
        kind = self.peek()
        if kind == 'int':
            self.advance()
            return ('int',)
        if kind == 'true' or kind == 'false':
            self.advance()
            return ('bool',)
        if kind == 'id':
            return ('var', self.advance()[1])
        if kind == '[':
            self.advance()
            self.expect(']')
            return ('nil',)
        if kind == '(':
            self.advance()
            first = self.parse_expr()
            if self.peek() == ',':
                self.advance()
                second = self.parse_expr()
                self.expect(')')
                return ('pair', first, second)
            self.expect(')')
            return first
        raise SyntaxError('unexpected token %s' % kind)


class _TVar:
    __slots__ = ('link', 'level')

    def __init__(self, level):
        self.link = None
        self.level = level


class _TCon:
    __slots__ = ('name', 'args')

    def __init__(self, name, args=()):
        self.name = name
        self.args = args


_INT = _TCon('int')
_BOOL = _TCon('bool')


def _arrow(left, right):
    return _TCon('->', (left, right))


def _list(elem):
    return _TCon('list', (elem,))


def _tuple(left, right):
    return _TCon('*', (left, right))


def _prune(node):
    root = node
    while type(root) is _TVar and root.link is not None:
        root = root.link
    while type(node) is _TVar and node.link is not None:
        nxt = node.link
        node.link = root
        node = nxt
    return root


def _bind(var, target):
    stack = [target]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if node is var:
            raise TypeError('occurs check')
        if type(node) is _TVar:
            if node.level > var.level:
                node.level = var.level
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node.args)
    var.link = target


def _unify(first, second):
    stack = [(first, second)]
    while stack:
        left, right = stack.pop()
        left = _prune(left)
        right = _prune(right)
        if left is right:
            continue
        if type(left) is _TVar:
            _bind(left, right)
        elif type(right) is _TVar:
            _bind(right, left)
        else:
            if left.name != right.name or len(left.args) != len(right.args):
                raise TypeError('type mismatch')
            for pair in zip(left.args, right.args):
                stack.append(pair)


def _generalize(node, level):
    poly = False
    stack = [node]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _TVar:
            if cur.level > level:
                cur.level = _GENERIC
                poly = True
        else:
            key = id(cur)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(cur.args)
    return poly


def _instantiate(node, level):
    memo = {}

    def copy(cur):
        cur = _prune(cur)
        if type(cur) is _TVar:
            if cur.level == _GENERIC:
                key = id(cur)
                fresh = memo.get(key)
                if fresh is None:
                    fresh = _TVar(level)
                    memo[key] = fresh
                return fresh
            return cur
        if not cur.args:
            return cur
        key = id(cur)
        done = memo.get(key)
        if done is not None:
            return done
        new_args = tuple(copy(arg) for arg in cur.args)
        same = True
        for old, new in zip(cur.args, new_args):
            if old is not new:
                same = False
                break
        result = cur if same else _TCon(cur.name, new_args)
        memo[key] = result
        return result

    return copy(node)


def _builtin_env():
    def gen():
        return _TVar(_GENERIC)

    env = {}
    a = gen()
    b = gen()
    env['fst'] = (_arrow(_tuple(a, b), a), True)
    a = gen()
    b = gen()
    env['snd'] = (_arrow(_tuple(a, b), b), True)
    a = gen()
    env['hd'] = (_arrow(_list(a), a), True)
    a = gen()
    env['tl'] = (_arrow(_list(a), _list(a)), True)
    a = gen()
    env['null'] = (_arrow(_list(a), _BOOL), True)
    return env


_MISSING = object()


def _infer_node(node, env, level):
    tag = node[0]
    if tag == 'int':
        return _INT
    if tag == 'bool':
        return _BOOL
    if tag == 'var':
        entry = env.get(node[1])
        if entry is None:
            raise NameError(node[1])
        node_type, poly = entry
        if poly:
            return _instantiate(node_type, level)
        return node_type
    if tag == 'nil':
        return _list(_TVar(level))
    if tag == 'lam':
        param = _TVar(level)
        old = env.get(node[1], _MISSING)
        env[node[1]] = (param, False)
        body_type = _infer_node(node[2], env, level)
        if old is _MISSING:
            del env[node[1]]
        else:
            env[node[1]] = old
        return _arrow(param, body_type)
    if tag == 'app':
        func_type = _infer_node(node[1], env, level)
        arg_type = _infer_node(node[2], env, level)
        result = _TVar(level)
        _unify(func_type, _arrow(arg_type, result))
        return result
    if tag == 'bin':
        op = node[1]
        left_type = _infer_node(node[2], env, level)
        right_type = _infer_node(node[3], env, level)
        if op == '=':
            _unify(left_type, right_type)
            return _BOOL
        _unify(left_type, _INT)
        _unify(right_type, _INT)
        return _BOOL if op == '<' else _INT
    if tag == 'cons':
        head_type = _infer_node(node[1], env, level)
        tail_type = _infer_node(node[2], env, level)
        _unify(tail_type, _list(head_type))
        return tail_type
    if tag == 'pair':
        first = _infer_node(node[1], env, level)
        second = _infer_node(node[2], env, level)
        return _tuple(first, second)
    if tag == 'if':
        cond_type = _infer_node(node[1], env, level)
        _unify(cond_type, _BOOL)
        then_type = _infer_node(node[2], env, level)
        else_type = _infer_node(node[3], env, level)
        _unify(then_type, else_type)
        return then_type
    if tag == 'let':
        name = node[1]
        bound_type = _infer_node(node[2], env, level + 1)
        poly = _generalize(bound_type, level)
        old = env.get(name, _MISSING)
        env[name] = (bound_type, poly)
        result = _infer_node(node[3], env, level)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return result
    if tag == 'letrec':
        name = node[1]
        old = env.get(name, _MISSING)
        self_type = _TVar(level + 1)
        env[name] = (self_type, False)
        bound_type = _infer_node(node[2], env, level + 1)
        _unify(self_type, bound_type)
        poly = _generalize(self_type, level)
        env[name] = (self_type, poly)
        result = _infer_node(node[3], env, level)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return result
    raise SyntaxError('bad node')


def _var_name(index):
    letter = chr(97 + index % 26)
    if index >= 26:
        return letter + str(index // 26)
    return letter


def _show(node, ctx, names):
    node = _prune(node)
    if type(node) is _TVar:
        key = id(node)
        name = names.get(key)
        if name is None:
            name = "'" + _var_name(len(names))
            names[key] = name
        return name
    kind = node.name
    if kind == 'int' or kind == 'bool':
        return kind
    if kind == 'list':
        return _show(node.args[0], 3, names) + ' list'
    if kind == '->':
        left = _show(node.args[0], 1, names)
        right = _show(node.args[1], 0, names)
        text = left + ' -> ' + right
        return '(' + text + ')' if ctx >= 1 else text
    left = _show(node.args[0], 2, names)
    right = _show(node.args[1], 2, names)
    text = left + ' * ' + right
    return '(' + text + ')' if ctx >= 2 else text


def _infer_impl(src):
    tokens = _tokenize(src)
    parser = _Parser(tokens)
    tree = parser.parse_expr()
    if parser.peek() != 'eof':
        raise SyntaxError('trailing tokens')
    env = _builtin_env()
    result = _infer_node(tree, env, 0)
    return _show(result, 0, {})


def _run_deep(func, *args):
    box = {}

    def target():
        try:
            box['value'] = func(*args)
        except BaseException as exc:
            box['error'] = exc

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 400000))
    old_stack = None
    try:
        try:
            old_stack = threading.stack_size(128 * 1024 * 1024)
        except (ValueError, RuntimeError):
            old_stack = None
        started = False
        thread = None
        try:
            thread = threading.Thread(target=target)
            thread.start()
            started = True
        except RuntimeError:
            started = False
        if started:
            thread.join()
        else:
            target()
    finally:
        if old_stack is not None:
            try:
                threading.stack_size(old_stack)
            except (ValueError, RuntimeError):
                pass
        sys.setrecursionlimit(old_limit)
    if 'error' in box:
        raise box['error']
    return box['value']


def infer(src: str) -> str:
    return _run_deep(_infer_impl, src)
```
