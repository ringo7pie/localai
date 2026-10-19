```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GEN = 10 ** 9


def _lex(src):
    tokens = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch in " \t\n":
            pos += 1
        elif "0" <= ch <= "9":
            start = pos
            while pos < length and "0" <= src[pos] <= "9":
                pos += 1
            tokens.append(("int", src[start:pos]))
        elif ("a" <= ch <= "z") or ch == "_":
            start = pos
            pos += 1
            while pos < length and (
                ("a" <= src[pos] <= "z")
                or ("A" <= src[pos] <= "Z")
                or ("0" <= src[pos] <= "9")
                or src[pos] in "_'"
            ):
                pos += 1
            word = src[start:pos]
            if word in _KEYWORDS:
                tokens.append(("op", word))
            else:
                tokens.append(("name", word))
        elif src.startswith("->", pos):
            tokens.append(("op", "->"))
            pos += 2
        elif src.startswith("::", pos):
            tokens.append(("op", "::"))
            pos += 2
        elif ch in "(),+-*=<[]":
            tokens.append(("op", ch))
            pos += 1
        else:
            raise SyntaxError("bad character %r" % ch)
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return ("eof", "")

    def advance(self):
        token = self.peek()
        self.pos += 1
        return token

    def is_op(self, text):
        return self.peek() == ("op", text)

    def expect(self, text):
        if not self.is_op(text):
            raise SyntaxError("expected " + text)
        self.pos += 1

    def parse_all(self):
        expr = self.parse_expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("unexpected token")
        return expr

    def parse_params(self):
        params = []
        while self.peek()[0] == "name":
            params.append(self.advance()[1])
        return params

    @staticmethod
    def make_lam(params, body):
        for param in reversed(params):
            body = ("lam", param, body)
        return body

    def parse_expr(self):
        token = self.peek()
        if token == ("op", "fun"):
            self.advance()
            params = self.parse_params()
            if not params:
                raise SyntaxError("fun needs parameters")
            self.expect("->")
            body = self.parse_expr()
            return self.make_lam(params, body)
        if token == ("op", "let"):
            self.advance()
            is_rec = False
            if self.is_op("rec"):
                self.advance()
                is_rec = True
            name_token = self.advance()
            if name_token[0] != "name":
                raise SyntaxError("expected name")
            params = self.parse_params()
            if is_rec and not params:
                raise SyntaxError("let rec needs parameters")
            self.expect("=")
            bound = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            bound = self.make_lam(params, bound)
            if is_rec:
                return ("letrec", name_token[1], bound, body)
            return ("let", name_token[1], bound, body)
        if token == ("op", "if"):
            self.advance()
            cond = self.parse_expr()
            self.expect("then")
            then_branch = self.parse_expr()
            self.expect("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.peek() in (("op", "="), ("op", "<")):
            op = self.advance()[1]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        operands = [self.parse_add()]
        while self.is_op("::"):
            self.advance()
            operands.append(self.parse_add())
        result = operands[-1]
        for operand in reversed(operands[:-1]):
            result = ("bin", "::", operand, result)
        return result

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.advance()[1]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_op("*"):
            self.advance()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def starts_atom(self):
        token = self.peek()
        if token[0] in ("int", "name"):
            return True
        return token in (("op", "true"), ("op", "false"), ("op", "("), ("op", "["))

    def parse_app(self):
        left = self.parse_atom()
        while self.starts_atom():
            right = self.parse_atom()
            left = ("app", left, right)
        return left

    def parse_atom(self):
        token = self.advance()
        kind, value = token
        if kind == "int":
            return ("int",)
        if kind == "name":
            return ("var", value)
        if token == ("op", "true") or token == ("op", "false"):
            return ("bool",)
        if token == ("op", "["):
            self.expect("]")
            return ("nil",)
        if token == ("op", "("):
            first = self.parse_expr()
            if self.is_op(","):
                self.advance()
                second = self.parse_expr()
                self.expect(")")
                return ("tuple", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


class _TVar:
    __slots__ = ("level", "link")

    def __init__(self, level):
        self.level = level
        self.link = None


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = tuple(args)


_INT = _TCon("int")
_BOOL = _TCon("bool")


def _fn(arg, result):
    return _TCon("->", (arg, result))


def _prune(typ):
    root = typ
    while type(root) is _TVar and root.link is not None:
        root = root.link
    while type(typ) is _TVar and typ.link is not None:
        nxt = typ.link
        typ.link = root
        typ = nxt
    return root


def _adjust(var, typ):
    typ = _prune(typ)
    if type(typ) is _TVar:
        if typ is var:
            raise TypeError("occurs check")
        if typ.level > var.level:
            typ.level = var.level
    else:
        for arg in typ.args:
            _adjust(var, arg)


def _unify(left, right):
    left = _prune(left)
    right = _prune(right)
    if left is right:
        return
    if type(left) is _TVar:
        _adjust(left, right)
        left.link = right
        return
    if type(right) is _TVar:
        _adjust(right, left)
        right.link = left
        return
    if left.name != right.name or len(left.args) != len(right.args):
        raise TypeError("type mismatch")
    for left_arg, right_arg in zip(left.args, right.args):
        _unify(left_arg, right_arg)


def _instantiate(typ, mapping):
    typ = _prune(typ)
    if type(typ) is _TVar:
        if typ.level == _GEN:
            if typ not in mapping:
                mapping[typ] = _TVar(_CURRENT_LEVEL[0])
            return mapping[typ]
        return typ
    if not typ.args:
        return typ
    return _TCon(typ.name, [_instantiate(arg, mapping) for arg in typ.args])


def _generalize(typ, level):
    typ = _prune(typ)
    if type(typ) is _TVar:
        if typ.level > level:
            typ.level = _GEN
    else:
        for arg in typ.args:
            _generalize(arg, level)


_CURRENT_LEVEL = [0]


def _builtin_env():
    a = _TVar(_GEN)
    b = _TVar(_GEN)
    pair = _TCon("*", (a, b))
    list_a = _TCon("list", (a,))
    return {
        "fst": _fn(pair, a),
        "snd": _fn(pair, b),
        "hd": _fn(list_a, a),
        "tl": _fn(list_a, list_a),
        "null": _fn(list_a, _BOOL),
    }


def _infer(expr, env, level):
    kind = expr[0]
    if kind == "int":
        return _INT
    if kind == "bool":
        return _BOOL
    if kind == "nil":
        return _TCon("list", (_TVar(level),))
    if kind == "var":
        if expr[1] not in env:
            raise NameError(expr[1])
        _CURRENT_LEVEL[0] = level
        return _instantiate(env[expr[1]], {})
    if kind == "lam":
        param_type = _TVar(level)
        name = expr[1]
        missing = object()
        old = env.get(name, missing)
        env[name] = param_type
        try:
            body_type = _infer(expr[2], env, level)
        finally:
            if old is missing:
                del env[name]
            else:
                env[name] = old
        return _fn(param_type, body_type)
    if kind == "app":
        func_type = _infer(expr[1], env, level)
        arg_type = _infer(expr[2], env, level)
        result = _TVar(level)
        _unify(func_type, _fn(arg_type, result))
        return result
    if kind == "tuple":
        first = _infer(expr[1], env, level)
        second = _infer(expr[2], env, level)
        return _TCon("*", (first, second))
    if kind == "bin":
        op = expr[1]
        left = _infer(expr[2], env, level)
        right = _infer(expr[3], env, level)
        if op in ("+", "-", "*"):
            _unify(left, _INT)
            _unify(right, _INT)
            return _INT
        if op == "<":
            _unify(left, _INT)
            _unify(right, _INT)
            return _BOOL
        if op == "=":
            _unify(left, right)
            return _BOOL
        _unify(right, _TCon("list", (left,)))
        return right
    if kind == "if":
        cond = _infer(expr[1], env, level)
        _unify(cond, _BOOL)
        then_type = _infer(expr[2], env, level)
        else_type = _infer(expr[3], env, level)
        _unify(then_type, else_type)
        return then_type
    if kind == "let" or kind == "letrec":
        name = expr[1]
        if kind == "let":
            bound_type = _infer(expr[2], env, level + 1)
            _generalize(bound_type, level)
            binding = bound_type
            missing = object()
            old = env.get(name, missing)
        else:
            missing = object()
            old = env.get(name, missing)
            binding = _TVar(level + 1)
            env[name] = binding
            try:
                bound_type = _infer(expr[2], env, level + 1)
                _unify(binding, bound_type)
            except BaseException:
                if old is missing:
                    del env[name]
                else:
                    env[name] = old
                raise
            _generalize(binding, level)
        env[name] = binding
        try:
            return _infer(expr[3], env, level)
        finally:
            if old is missing:
                del env[name]
            else:
                env[name] = old
    raise SyntaxError("unknown node")


def _collect(typ, order, seen):
    typ = _prune(typ)
    if type(typ) is _TVar:
        if typ not in seen:
            seen[typ] = len(order)
            order.append(typ)
    else:
        for arg in typ.args:
            _collect(arg, order, seen)


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    if index >= 26:
        return "'" + letter + str(index // 26)
    return "'" + letter


def _format(typ, prec, names):
    typ = _prune(typ)
    if type(typ) is _TVar:
        return names[typ]
    if typ.name in ("int", "bool"):
        return typ.name
    if typ.name == "list":
        return _format(typ.args[0], 2, names) + " list"
    if typ.name == "->":
        text = _format(typ.args[0], 3, names) + " -> " + _format(typ.args[1], 0, names)
        return "(" + text + ")" if prec >= 1 else text
    text = _format(typ.args[0], 1, names) + " * " + _format(typ.args[1], 1, names)
    return "(" + text + ")" if prec in (1, 2) else text


def _run(src):
    tokens = _lex(src)
    ast = _Parser(tokens).parse_all()
    _CURRENT_LEVEL[0] = 0
    result = _infer(ast, _builtin_env(), 0)
    order = []
    seen = {}
    _collect(result, order, seen)
    names = {var: _var_name(index) for index, var in enumerate(order)}
    return _format(result, 0, names)


def infer(src: str) -> str:
    outcome = {}

    def worker():
        try:
            outcome["value"] = _run(src)
        except BaseException as error:
            outcome["error"] = error

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000000)
    old_stack = threading.stack_size()
    try:
        threading.stack_size(512 * 1024 * 1024)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    finally:
        threading.stack_size(old_stack)
        sys.setrecursionlimit(old_limit)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
