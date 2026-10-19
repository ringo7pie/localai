```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 10 ** 9


def _tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n":
            i += 1
        elif "0" <= c <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            toks.append(("int", src[i:j]))
            i = j
        elif ("a" <= c <= "z") or c == "_":
            j = i + 1
            while j < n and (("a" <= src[j] <= "z") or ("A" <= src[j] <= "Z")
                             or ("0" <= src[j] <= "9") or src[j] in "_'"):
                j += 1
            word = src[i:j]
            toks.append(("kw" if word in _KEYWORDS else "name", word))
            i = j
        elif c == "-":
            if i + 1 < n and src[i + 1] == ">":
                toks.append(("sym", "->"))
                i += 2
            else:
                toks.append(("sym", "-"))
                i += 1
        elif c == ":":
            if i + 1 < n and src[i + 1] == ":":
                toks.append(("sym", "::"))
                i += 2
            else:
                raise SyntaxError("bad ':'")
        elif c == "[":
            toks.append(("sym", "["))
            i += 1
        elif c in "(),+*=<]":
            toks.append(("sym", c))
            i += 1
        else:
            raise SyntaxError("bad char")
    return toks


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        if self.pos < len(self.toks):
            return self.toks[self.pos]
        return ("eof", "")

    def next(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def is_sym(self, value):
        return self.peek() == ("sym", value)

    def is_kw(self, value):
        return self.peek() == ("kw", value)

    def expect_sym(self, value):
        if not self.is_sym(value):
            raise SyntaxError("expected " + value)
        self.pos += 1

    def expect_kw(self, value):
        if not self.is_kw(value):
            raise SyntaxError("expected " + value)
        self.pos += 1

    def expect_name(self):
        tok = self.next()
        if tok[0] != "name":
            raise SyntaxError("expected name")
        return tok[1]

    def parse_all(self):
        expr = self.parse_expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("trailing tokens")
        return expr

    def parse_expr(self):
        tok = self.peek()
        if tok == ("kw", "fun"):
            self.pos += 1
            params = []
            while self.peek()[0] == "name":
                params.append(self.next()[1])
            if not params:
                raise SyntaxError("fun needs params")
            self.expect_sym("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if tok == ("kw", "let"):
            self.pos += 1
            is_rec = False
            if self.is_kw("rec"):
                self.pos += 1
                is_rec = True
            name = self.expect_name()
            params = []
            while self.peek()[0] == "name":
                params.append(self.next()[1])
            if is_rec and not params:
                raise SyntaxError("let rec needs params")
            self.expect_sym("=")
            bound = self.parse_expr()
            self.expect_kw("in")
            body = self.parse_expr()
            if params:
                bound = ("fun", params, bound)
            if is_rec:
                return ("letrec", name, bound, body)
            return ("let", name, bound, body)
        if tok == ("kw", "if"):
            self.pos += 1
            cond = self.parse_expr()
            self.expect_kw("then")
            then_expr = self.parse_expr()
            self.expect_kw("else")
            else_expr = self.parse_expr()
            return ("if", cond, then_expr, else_expr)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.peek() in (("sym", "="), ("sym", "<")):
            op = self.next()[1]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        left = self.parse_add()
        if self.is_sym("::"):
            self.pos += 1
            right = self.parse_cons()
            return ("bin", "::", left, right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() in (("sym", "+"), ("sym", "-")):
            op = self.next()[1]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_sym("*"):
            self.pos += 1
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def starts_atom(self):
        kind, value = self.peek()
        if kind in ("int", "name"):
            return True
        if kind == "kw":
            return value in ("true", "false")
        return kind == "sym" and value in ("(", "[")

    def parse_app(self):
        func = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        kind, value = self.next()
        if kind == "int":
            return ("int",)
        if kind == "name":
            return ("var", value)
        if kind == "kw" and value in ("true", "false"):
            return ("bool",)
        if kind == "sym" and value == "[":
            self.expect_sym("]")
            return ("nil",)
        if kind == "sym" and value == "(":
            first = self.parse_expr()
            if self.is_sym(","):
                self.pos += 1
                second = self.parse_expr()
                self.expect_sym(")")
                return ("tuple", first, second)
            self.expect_sym(")")
            return first
        raise SyntaxError("unexpected token")


class _TVar:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = tuple(args)


_INT = _TCon("int")
_BOOL = _TCon("bool")


def _arrow(left, right):
    return _TCon("->", (left, right))


def _prune(typ):
    while isinstance(typ, _TVar) and typ.ref is not None:
        typ = typ.ref
    return typ


def _occurs_adjust(var, typ):
    typ = _prune(typ)
    if isinstance(typ, _TVar):
        if typ is var:
            return True
        if typ.level > var.level:
            typ.level = var.level
        return False
    for arg in typ.args:
        if _occurs_adjust(var, arg):
            return True
    return False


def _unify(left, right):
    left = _prune(left)
    right = _prune(right)
    if left is right:
        return
    if isinstance(left, _TVar):
        if _occurs_adjust(left, right):
            raise TypeError("occurs check")
        left.ref = right
        return
    if isinstance(right, _TVar):
        if _occurs_adjust(right, left):
            raise TypeError("occurs check")
        right.ref = left
        return
    if left.name != right.name or len(left.args) != len(right.args):
        raise TypeError("mismatch")
    for a, b in zip(left.args, right.args):
        _unify(a, b)


def _generalize(typ, level):
    typ = _prune(typ)
    if isinstance(typ, _TVar):
        if typ.level > level:
            typ.level = _GENERIC
        return
    for arg in typ.args:
        _generalize(arg, level)


def _instantiate(typ, level, mapping):
    typ = _prune(typ)
    if isinstance(typ, _TVar):
        if typ.level == _GENERIC:
            if typ not in mapping:
                mapping[typ] = _TVar(level)
            return mapping[typ]
        return typ
    if not typ.args:
        return typ
    new_args = [_instantiate(arg, level, mapping) for arg in typ.args]
    changed = False
    for old, new in zip(typ.args, new_args):
        if old is not new:
            changed = True
            break
    if not changed:
        return typ
    return _TCon(typ.name, new_args)


def _lookup(env, name):
    while env is not None:
        if env[0] == name:
            return env[1]
        env = env[2]
    return None


def _builtin_env():
    def fresh():
        return _TVar(_GENERIC)

    a = fresh()
    b = fresh()
    fst_t = _arrow(_TCon("*", (a, b)), a)
    a2 = fresh()
    b2 = fresh()
    snd_t = _arrow(_TCon("*", (a2, b2)), b2)
    a3 = fresh()
    hd_t = _arrow(_TCon("list", (a3,)), a3)
    a4 = fresh()
    tl_t = _arrow(_TCon("list", (a4,)), _TCon("list", (a4,)))
    a5 = fresh()
    null_t = _arrow(_TCon("list", (a5,)), _BOOL)
    env = None
    for name, typ in (("fst", fst_t), ("snd", snd_t), ("hd", hd_t),
                      ("tl", tl_t), ("null", null_t)):
        env = (name, typ, env)
    return env


def _infer(env, expr, level):
    tag = expr[0]
    if tag == "int":
        return _INT
    if tag == "bool":
        return _BOOL
    if tag == "var":
        scheme = _lookup(env, expr[1])
        if scheme is None:
            raise NameError(expr[1])
        return _instantiate(scheme, level, {})
    if tag == "nil":
        return _TCon("list", (_TVar(level),))
    if tag == "fun":
        params = expr[1]
        param_types = []
        inner = env
        for name in params:
            var = _TVar(level)
            param_types.append(var)
            inner = (name, var, inner)
        result = _infer(inner, expr[2], level)
        for var in reversed(param_types):
            result = _arrow(var, result)
        return result
    if tag == "app":
        func_t = _infer(env, expr[1], level)
        arg_t = _infer(env, expr[2], level)
        result = _TVar(level)
        _unify(func_t, _arrow(arg_t, result))
        return result
    if tag == "let":
        bound_t = _infer(env, expr[2], level + 1)
        _generalize(bound_t, level)
        return _infer((expr[1], bound_t, env), expr[3], level)
    if tag == "letrec":
        self_t = _TVar(level + 1)
        inner = (expr[1], self_t, env)
        bound_t = _infer(inner, expr[2], level + 1)
        _unify(self_t, bound_t)
        _generalize(self_t, level)
        return _infer((expr[1], self_t, env), expr[3], level)
    if tag == "if":
        cond_t = _infer(env, expr[1], level)
        _unify(cond_t, _BOOL)
        then_t = _infer(env, expr[2], level)
        else_t = _infer(env, expr[3], level)
        _unify(then_t, else_t)
        return then_t
    if tag == "tuple":
        first = _infer(env, expr[1], level)
        second = _infer(env, expr[2], level)
        return _TCon("*", (first, second))
    if tag == "bin":
        op = expr[1]
        left_t = _infer(env, expr[2], level)
        right_t = _infer(env, expr[3], level)
        if op in ("+", "-", "*"):
            _unify(left_t, _INT)
            _unify(right_t, _INT)
            return _INT
        if op == "<":
            _unify(left_t, _INT)
            _unify(right_t, _INT)
            return _BOOL
        if op == "=":
            _unify(left_t, right_t)
            return _BOOL
        list_t = _TCon("list", (left_t,))
        _unify(right_t, list_t)
        return list_t
    raise SyntaxError("unknown node")


def _var_name(index):
    letter = chr(97 + index % 26)
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix else "")


def _show(typ, names, ctx):
    typ = _prune(typ)
    if isinstance(typ, _TVar):
        if typ not in names:
            names[typ] = _var_name(len(names))
        return names[typ]
    if typ.name == "->":
        text = (_show(typ.args[0], names, 1) + " -> "
                + _show(typ.args[1], names, 0))
        return "(" + text + ")" if ctx >= 1 else text
    if typ.name == "*":
        text = (_show(typ.args[0], names, 2) + " * "
                + _show(typ.args[1], names, 2))
        return "(" + text + ")" if ctx >= 2 else text
    if typ.name == "list":
        return _show(typ.args[0], names, 3) + " list"
    return typ.name


def _run(src):
    expr = _Parser(_tokenize(src)).parse_all()
    typ = _infer(_builtin_env(), expr, 0)
    return _show(typ, {}, 0)


def infer(src: str) -> str:
    box = {}

    def worker():
        try:
            box["value"] = _run(src)
        except BaseException as error:
            box["error"] = error

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
    if "error" in box:
        raise box["error"]
    return box["value"]
```
