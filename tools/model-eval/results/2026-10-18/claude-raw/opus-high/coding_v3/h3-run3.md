```python
import sys
import threading

_KEYWORDS = frozenset(['fun', 'let', 'rec', 'in', 'if', 'then', 'else', 'true', 'false'])
_GENERIC = 1 << 60
_MISSING = object()


def _is_lower(ch):
    return 'a' <= ch <= 'z'


def _is_name_char(ch):
    return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z') or ('0' <= ch <= '9') or ch == '_' or ch == "'"


def _tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in ' \t\n\r':
            i += 1
            continue
        if '0' <= ch <= '9':
            j = i
            while j < n and '0' <= src[j] <= '9':
                j += 1
            toks.append(('int', src[i:j]))
            i = j
            continue
        if _is_lower(ch) or ch == '_':
            j = i + 1
            while j < n and _is_name_char(src[j]):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append(('kw', word))
            else:
                toks.append(('name', word))
            i = j
            continue
        if ch == '-':
            if i + 1 < n and src[i + 1] == '>':
                toks.append(('sym', '->'))
                i += 2
            else:
                toks.append(('sym', '-'))
                i += 1
            continue
        if ch == ':':
            if i + 1 < n and src[i + 1] == ':':
                toks.append(('sym', '::'))
                i += 2
                continue
            raise SyntaxError("unexpected ':'")
        if ch == '[':
            if i + 1 < n and src[i + 1] == ']':
                toks.append(('sym', '[]'))
                i += 2
                continue
            raise SyntaxError("'[' must be followed by ']'")
        if ch in '()+*=<,':
            toks.append(('sym', ch))
            i += 1
            continue
        raise SyntaxError("unexpected character %r" % ch)
    toks.append(('eof', None))
    return toks


def _mkfun(params, body):
    for param in reversed(params):
        body = ('fun', param, body)
    return body


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def advance(self):
        tok = self.toks[self.pos]
        if tok[0] != 'eof':
            self.pos += 1
        return tok

    def expect(self, kind, value):
        tok = self.toks[self.pos]
        if tok[0] != kind or tok[1] != value:
            raise SyntaxError("expected %r" % (value,))
        self.pos += 1

    def parse(self):
        expr = self.expr()
        if self.peek()[0] != 'eof':
            raise SyntaxError("unexpected token %r" % (self.peek()[1],))
        return expr

    def expr(self):
        kind, value = self.peek()
        if kind == 'kw':
            if value == 'fun':
                self.pos += 1
                params = []
                while self.peek()[0] == 'name':
                    params.append(self.advance()[1])
                if not params:
                    raise SyntaxError("fun needs a parameter")
                self.expect('sym', '->')
                body = self.expr()
                return _mkfun(params, body)
            if value == 'let':
                self.pos += 1
                is_rec = False
                if self.peek() == ('kw', 'rec'):
                    is_rec = True
                    self.pos += 1
                if self.peek()[0] != 'name':
                    raise SyntaxError("let needs a name")
                name = self.advance()[1]
                params = []
                while self.peek()[0] == 'name':
                    params.append(self.advance()[1])
                if is_rec and not params:
                    raise SyntaxError("let rec needs a parameter")
                self.expect('sym', '=')
                bound = self.expr()
                self.expect('kw', 'in')
                body = self.expr()
                if params:
                    bound = _mkfun(params, bound)
                return ('letrec' if is_rec else 'let', name, bound, body)
            if value == 'if':
                self.pos += 1
                cond = self.expr()
                self.expect('kw', 'then')
                then_branch = self.expr()
                self.expect('kw', 'else')
                else_branch = self.expr()
                return ('if', cond, then_branch, else_branch)
        return self.compare()

    def compare(self):
        left = self.cons()
        while True:
            tok = self.peek()
            if tok == ('sym', '=') or tok == ('sym', '<'):
                self.pos += 1
                right = self.cons()
                left = ('bin', tok[1], left, right)
            else:
                return left

    def cons(self):
        items = [self.additive()]
        while self.peek() == ('sym', '::'):
            self.pos += 1
            items.append(self.additive())
        result = items[-1]
        for index in range(len(items) - 2, -1, -1):
            result = ('bin', '::', items[index], result)
        return result

    def additive(self):
        left = self.multiplicative()
        while True:
            tok = self.peek()
            if tok == ('sym', '+') or tok == ('sym', '-'):
                self.pos += 1
                right = self.multiplicative()
                left = ('bin', tok[1], left, right)
            else:
                return left

    def multiplicative(self):
        left = self.application()
        while self.peek() == ('sym', '*'):
            self.pos += 1
            right = self.application()
            left = ('bin', '*', left, right)
        return left

    def _starts_atom(self, tok):
        kind, value = tok
        if kind == 'int' or kind == 'name':
            return True
        if kind == 'kw' and (value == 'true' or value == 'false'):
            return True
        if kind == 'sym' and (value == '(' or value == '[]'):
            return True
        return False

    def application(self):
        func = self.atom()
        while self._starts_atom(self.peek()):
            arg = self.atom()
            func = ('app', func, arg)
        return func

    def atom(self):
        kind, value = self.peek()
        if kind == 'int':
            self.pos += 1
            return ('int',)
        if kind == 'name':
            self.pos += 1
            return ('var', value)
        if kind == 'kw' and (value == 'true' or value == 'false'):
            self.pos += 1
            return ('bool',)
        if kind == 'sym' and value == '[]':
            self.pos += 1
            return ('nil',)
        if kind == 'sym' and value == '(':
            self.pos += 1
            first = self.expr()
            if self.peek() == ('sym', ','):
                self.pos += 1
                second = self.expr()
                self.expect('sym', ')')
                return ('pair', first, second)
            self.expect('sym', ')')
            return first
        raise SyntaxError("unexpected token %r" % (value,))


def _check_names(expr, scope):
    tag = expr[0]
    if tag == 'var':
        if scope.get(expr[1], 0) <= 0:
            raise NameError("name %r is not defined" % expr[1])
        return
    if tag in ('int', 'bool', 'nil'):
        return
    if tag == 'fun':
        name = expr[1]
        scope[name] = scope.get(name, 0) + 1
        _check_names(expr[2], scope)
        scope[name] -= 1
        return
    if tag == 'let':
        _check_names(expr[2], scope)
        name = expr[1]
        scope[name] = scope.get(name, 0) + 1
        _check_names(expr[3], scope)
        scope[name] -= 1
        return
    if tag == 'letrec':
        name = expr[1]
        scope[name] = scope.get(name, 0) + 1
        _check_names(expr[2], scope)
        _check_names(expr[3], scope)
        scope[name] -= 1
        return
    if tag in ('app', 'pair'):
        _check_names(expr[1], scope)
        _check_names(expr[2], scope)
        return
    if tag == 'if':
        _check_names(expr[1], scope)
        _check_names(expr[2], scope)
        _check_names(expr[3], scope)
        return
    if tag == 'bin':
        _check_names(expr[2], scope)
        _check_names(expr[3], scope)
        return
    raise SyntaxError("bad node")


class _TVar:
    __slots__ = ('inst', 'level')

    def __init__(self, level):
        self.inst = None
        self.level = level


_INT = ('int',)
_BOOL = ('bool',)


def _prune(typ):
    if not isinstance(typ, _TVar) or typ.inst is None:
        return typ
    root = typ
    while isinstance(root, _TVar) and root.inst is not None:
        root = root.inst
    cur = typ
    while cur is not root:
        nxt = cur.inst
        cur.inst = root
        cur = nxt
    return root


def _bind(var, typ):
    level = var.level
    stack = [typ]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if isinstance(cur, _TVar):
            if cur is var:
                raise TypeError("recursive type")
            if cur.level > level:
                cur.level = level
        else:
            key = id(cur)
            if key in seen:
                continue
            seen.add(key)
            for index in range(1, len(cur)):
                stack.append(cur[index])
    var.inst = typ


def _unify(left, right):
    stack = [(left, right)]
    while stack:
        first, second = stack.pop()
        first = _prune(first)
        second = _prune(second)
        if first is second:
            continue
        if isinstance(first, _TVar):
            _bind(first, second)
            continue
        if isinstance(second, _TVar):
            _bind(second, first)
            continue
        if first[0] != second[0]:
            raise TypeError("cannot unify %s with %s" % (first[0], second[0]))
        for index in range(1, len(first)):
            stack.append((first[index], second[index]))


class _Inferer:
    def __init__(self):
        self.level = 0

    def fresh(self):
        return _TVar(self.level)

    def generalize(self, typ):
        stack = [typ]
        seen = set()
        current = self.level
        while stack:
            cur = _prune(stack.pop())
            if isinstance(cur, _TVar):
                if cur.level > current and cur.level != _GENERIC:
                    cur.level = _GENERIC
            else:
                key = id(cur)
                if key in seen:
                    continue
                seen.add(key)
                for index in range(1, len(cur)):
                    stack.append(cur[index])

    def instantiate(self, typ):
        var_memo = {}
        tuple_memo = {}
        level = self.level

        def copy(cur):
            cur = _prune(cur)
            if isinstance(cur, _TVar):
                if cur.level == _GENERIC:
                    replacement = var_memo.get(cur)
                    if replacement is None:
                        replacement = _TVar(level)
                        var_memo[cur] = replacement
                    return replacement
                return cur
            if len(cur) == 1:
                return cur
            key = id(cur)
            done = tuple_memo.get(key)
            if done is not None:
                return done
            if len(cur) == 2:
                result = (cur[0], copy(cur[1]))
            else:
                first = copy(cur[1])
                second = copy(cur[2])
                result = (cur[0], first, second)
            tuple_memo[key] = result
            return result

        return copy(typ)

    def infer(self, expr, env):
        tag = expr[0]
        if tag == 'int':
            return _INT
        if tag == 'bool':
            return _BOOL
        if tag == 'nil':
            return ('list', self.fresh())
        if tag == 'var':
            is_poly, typ = env[expr[1]]
            if is_poly:
                return self.instantiate(typ)
            return typ
        if tag == 'pair':
            first = self.infer(expr[1], env)
            second = self.infer(expr[2], env)
            return ('*', first, second)
        if tag == 'app':
            func_type = self.infer(expr[1], env)
            arg_type = self.infer(expr[2], env)
            result = self.fresh()
            _unify(func_type, ('->', arg_type, result))
            return result
        if tag == 'fun':
            name = expr[1]
            param = self.fresh()
            old = env.get(name, _MISSING)
            env[name] = (False, param)
            body_type = self.infer(expr[2], env)
            if old is _MISSING:
                del env[name]
            else:
                env[name] = old
            return ('->', param, body_type)
        if tag == 'let':
            name = expr[1]
            self.level += 1
            bound_type = self.infer(expr[2], env)
            self.level -= 1
            self.generalize(bound_type)
            old = env.get(name, _MISSING)
            env[name] = (True, bound_type)
            body_type = self.infer(expr[3], env)
            if old is _MISSING:
                del env[name]
            else:
                env[name] = old
            return body_type
        if tag == 'letrec':
            name = expr[1]
            old = env.get(name, _MISSING)
            self.level += 1
            self_type = self.fresh()
            env[name] = (False, self_type)
            bound_type = self.infer(expr[2], env)
            _unify(self_type, bound_type)
            self.level -= 1
            self.generalize(self_type)
            env[name] = (True, self_type)
            body_type = self.infer(expr[3], env)
            if old is _MISSING:
                del env[name]
            else:
                env[name] = old
            return body_type
        if tag == 'if':
            cond_type = self.infer(expr[1], env)
            _unify(cond_type, _BOOL)
            then_type = self.infer(expr[2], env)
            else_type = self.infer(expr[3], env)
            _unify(then_type, else_type)
            return then_type
        if tag == 'bin':
            op = expr[1]
            left = self.infer(expr[2], env)
            right = self.infer(expr[3], env)
            if op == '+' or op == '-' or op == '*':
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
            if op == '::':
                _unify(right, ('list', left))
                return right
        raise SyntaxError("bad node")


def _builtin_env():
    env = {}
    var_a = _TVar(_GENERIC)
    var_b = _TVar(_GENERIC)
    env['fst'] = (True, ('->', ('*', var_a, var_b), var_a))
    var_a = _TVar(_GENERIC)
    var_b = _TVar(_GENERIC)
    env['snd'] = (True, ('->', ('*', var_a, var_b), var_b))
    var_a = _TVar(_GENERIC)
    env['hd'] = (True, ('->', ('list', var_a), var_a))
    var_a = _TVar(_GENERIC)
    env['tl'] = (True, ('->', ('list', var_a), ('list', var_a)))
    var_a = _TVar(_GENERIC)
    env['null'] = (True, ('->', ('list', var_a), _BOOL))
    return env


def _show(typ):
    names = {}

    def name_of(var):
        label = names.get(var)
        if label is None:
            count = len(names)
            letter = chr(ord('a') + count % 26)
            suffix = '' if count < 26 else str(count // 26)
            label = "'" + letter + suffix
            names[var] = label
        return label

    def render(cur):
        cur = _prune(cur)
        if isinstance(cur, _TVar):
            return name_of(cur), 'atom'
        tag = cur[0]
        if tag == 'int' or tag == 'bool':
            return tag, 'atom'
        if tag == 'list':
            text, kind = render(cur[1])
            if kind == 'arrow' or kind == 'pair':
                text = '(' + text + ')'
            return text + ' list', 'atom'
        if tag == '*':
            left_text, left_kind = render(cur[1])
            right_text, right_kind = render(cur[2])
            if left_kind == 'arrow' or left_kind == 'pair':
                left_text = '(' + left_text + ')'
            if right_kind == 'arrow' or right_kind == 'pair':
                right_text = '(' + right_text + ')'
            return left_text + ' * ' + right_text, 'pair'
        if tag == '->':
            left_text, left_kind = render(cur[1])
            right_text, right_kind = render(cur[2])
            if left_kind == 'arrow':
                left_text = '(' + left_text + ')'
            return left_text + ' -> ' + right_text, 'arrow'
        raise TypeError("unknown type")

    return render(typ)[0]


def _infer_impl(src):
    toks = _tokenize(src)
    ast = _Parser(toks).parse()
    env = _builtin_env()
    scope = {}
    for name in env:
        scope[name] = 1
    _check_names(ast, scope)
    inferer = _Inferer()
    typ = inferer.infer(ast, env)
    return _show(typ)


def infer(src: str) -> str:
    outcome = {}

    def run():
        try:
            outcome['value'] = _infer_impl(src)
        except BaseException as exc:
            outcome['error'] = exc

    old_limit = sys.getrecursionlimit()
    if old_limit < 200000:
        sys.setrecursionlimit(200000)
    old_stack = None
    try:
        old_stack = threading.stack_size(256 * 1024 * 1024)
    except (ValueError, RuntimeError):
        old_stack = None
    try:
        worker = threading.Thread(target=run)
        worker.start()
        worker.join()
    finally:
        if old_stack is not None:
            try:
                threading.stack_size(old_stack)
            except (ValueError, RuntimeError):
                pass
        sys.setrecursionlimit(old_limit)
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']
```
