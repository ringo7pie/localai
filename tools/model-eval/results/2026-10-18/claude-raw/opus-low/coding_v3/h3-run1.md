```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 10 ** 9


def _lex(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch.isdigit() and ch.isascii():
            j = i
            while j < n and src[j].isascii() and src[j].isdigit():
                j += 1
            toks.append(("int", int(src[i:j])))
            i = j
            continue
        if ("a" <= ch <= "z") or ch == "_":
            j = i + 1
            while j < n and (src[j].isascii() and (src[j].isalnum()) or src[j] in "_'"):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append(("kw", word))
            else:
                toks.append(("name", word))
            i = j
            continue
        two = src[i:i + 2]
        if two in ("->", "::"):
            toks.append(("sym", two))
            i += 2
            continue
        if ch == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("nil", None))
                i += 2
                continue
            raise SyntaxError("bad [")
        if ch in "(),+-*=<":
            toks.append(("sym", ch))
            i += 1
            continue
        raise SyntaxError("bad char %r" % ch)
    toks.append(("eof", None))
    return toks


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def next(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind, val=None):
        tok = self.next()
        if tok[0] != kind or (val is not None and tok[1] != val):
            raise SyntaxError("expected %s %s" % (kind, val))
        return tok

    def is_tok(self, kind, val=None):
        tok = self.peek()
        return tok[0] == kind and (val is None or tok[1] == val)

    def parse_top(self):
        expr = self.parse_expr()
        if not self.is_tok("eof"):
            raise SyntaxError("trailing tokens")
        return expr

    def parse_name(self):
        tok = self.next()
        if tok[0] != "name":
            raise SyntaxError("expected name")
        return tok[1]

    def parse_params(self):
        params = []
        while self.is_tok("name"):
            params.append(self.next()[1])
        return params

    def parse_expr(self):
        if self.is_tok("kw", "fun"):
            self.next()
            params = self.parse_params()
            if not params:
                raise SyntaxError("fun needs params")
            self.expect("sym", "->")
            body = self.parse_expr()
            for param in reversed(params):
                body = ("fun", param, body)
            return body
        if self.is_tok("kw", "let"):
            self.next()
            rec = False
            if self.is_tok("kw", "rec"):
                self.next()
                rec = True
            name = self.parse_name()
            params = self.parse_params()
            if rec and not params:
                raise SyntaxError("let rec needs params")
            self.expect("sym", "=")
            rhs = self.parse_expr()
            self.expect("kw", "in")
            body = self.parse_expr()
            for param in reversed(params):
                rhs = ("fun", param, rhs)
            if rec:
                return ("letrec", name, rhs, body)
            return ("let", name, rhs, body)
        if self.is_tok("kw", "if"):
            self.next()
            cond = self.parse_expr()
            self.expect("kw", "then")
            thn = self.parse_expr()
            self.expect("kw", "else")
            els = self.parse_expr()
            return ("if", cond, thn, els)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.is_tok("sym", "=") or self.is_tok("sym", "<"):
            op = self.next()[1]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        items = [self.parse_add()]
        while self.is_tok("sym", "::"):
            self.next()
            items.append(self.parse_add())
        result = items[-1]
        for item in reversed(items[:-1]):
            result = ("bin", "::", item, result)
        return result

    def parse_add(self):
        left = self.parse_mul()
        while self.is_tok("sym", "+") or self.is_tok("sym", "-"):
            op = self.next()[1]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_tok("sym", "*"):
            self.next()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def starts_atom(self):
        tok = self.peek()
        if tok[0] in ("int", "name", "nil"):
            return True
        if tok[0] == "kw" and tok[1] in ("true", "false"):
            return True
        return tok[0] == "sym" and tok[1] == "("

    def parse_app(self):
        if not self.starts_atom():
            raise SyntaxError("expected expression")
        func = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        tok = self.next()
        kind, val = tok
        if kind == "int":
            return ("int", val)
        if kind == "name":
            return ("var", val)
        if kind == "nil":
            return ("nil",)
        if kind == "kw" and val in ("true", "false"):
            return ("bool", val == "true")
        if kind == "sym" and val == "(":
            first = self.parse_expr()
            if self.is_tok("sym", ","):
                self.next()
                second = self.parse_expr()
                self.expect("sym", ")")
                return ("pair", first, second)
            self.expect("sym", ")")
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


def _arrow(a, b):
    return _TCon("->", (a, b))


def _prune(t):
    while isinstance(t, _TVar) and t.ref is not None:
        t = t.ref
    return t


def _occurs_adjust(tv, t):
    t = _prune(t)
    if t is tv:
        raise TypeError("occurs check")
    if isinstance(t, _TVar):
        if t.level > tv.level:
            t.level = tv.level
        return
    for arg in t.args:
        _occurs_adjust(tv, arg)


def _unify(a, b):
    a = _prune(a)
    b = _prune(b)
    if a is b:
        return
    if isinstance(a, _TVar):
        _occurs_adjust(a, b)
        a.ref = b
        return
    if isinstance(b, _TVar):
        _occurs_adjust(b, a)
        b.ref = a
        return
    if a.name != b.name or len(a.args) != len(b.args):
        raise TypeError("type mismatch")
    for x, y in zip(a.args, b.args):
        _unify(x, y)


class _Infer:
    def __init__(self):
        self.level = 0

    def fresh(self):
        return _TVar(self.level)

    def generalize(self, t):
        t = _prune(t)
        if isinstance(t, _TVar):
            if t.level > self.level:
                t.level = _GENERIC
            return
        for arg in t.args:
            self.generalize(arg)

    def instantiate(self, t, mapping=None):
        if mapping is None:
            mapping = {}
        t = _prune(t)
        if isinstance(t, _TVar):
            if t.level == _GENERIC:
                if t not in mapping:
                    mapping[t] = self.fresh()
                return mapping[t]
            return t
        if not t.args:
            return t
        return _TCon(t.name, [self.instantiate(arg, mapping) for arg in t.args])

    def poly(self, build):
        self.level += 1
        t = build()
        self.level -= 1
        self.generalize(t)
        return t

    def infer(self, env, expr):
        kind = expr[0]
        if kind == "int":
            return _INT
        if kind == "bool":
            return _BOOL
        if kind == "nil":
            return _TCon("list", (self.fresh(),))
        if kind == "var":
            if expr[1] not in env:
                raise NameError(expr[1])
            return self.instantiate(env[expr[1]])
        if kind == "pair":
            return _TCon("*", (self.infer(env, expr[1]), self.infer(env, expr[2])))
        if kind == "fun":
            param_t = self.fresh()
            new_env = dict(env)
            new_env[expr[1]] = param_t
            return _arrow(param_t, self.infer(new_env, expr[2]))
        if kind == "app":
            func_t = self.infer(env, expr[1])
            arg_t = self.infer(env, expr[2])
            res = self.fresh()
            _unify(func_t, _arrow(arg_t, res))
            return res
        if kind == "bin":
            op = expr[1]
            left = self.infer(env, expr[2])
            right = self.infer(env, expr[3])
            if op in "+-*":
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
            _unify(_TCon("list", (left,)), right)
            return right
        if kind == "if":
            _unify(self.infer(env, expr[1]), _BOOL)
            thn = self.infer(env, expr[2])
            els = self.infer(env, expr[3])
            _unify(thn, els)
            return thn
        if kind == "let":
            rhs_t = self.poly(lambda: self.infer(env, expr[2]))
            new_env = dict(env)
            new_env[expr[1]] = rhs_t
            return self.infer(new_env, expr[3])
        if kind == "letrec":
            name = expr[1]

            def build():
                self_t = self.fresh()
                rec_env = dict(env)
                rec_env[name] = self_t
                body_t = self.infer(rec_env, expr[2])
                _unify(self_t, body_t)
                return self_t

            rhs_t = self.poly(build)
            new_env = dict(env)
            new_env[name] = rhs_t
            return self.infer(new_env, expr[3])
        raise SyntaxError("unknown node")


def _builtin_env():
    def gv():
        return _TVar(_GENERIC)

    env = {}
    a, b = gv(), gv()
    env["fst"] = _arrow(_TCon("*", (a, b)), a)
    a, b = gv(), gv()
    env["snd"] = _arrow(_TCon("*", (a, b)), b)
    a = gv()
    env["hd"] = _arrow(_TCon("list", (a,)), a)
    a = gv()
    env["tl"] = _arrow(_TCon("list", (a,)), _TCon("list", (a,)))
    a = gv()
    env["null"] = _arrow(_TCon("list", (a,)), _BOOL)
    return env


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix else "")


def _show(t, names):
    t = _prune(t)
    if isinstance(t, _TVar):
        if t not in names:
            names[t] = _var_name(len(names))
        return names[t]
    if t.name == "->":
        left_t = _prune(t.args[0])
        left = _show(left_t, names)
        if isinstance(left_t, _TCon) and left_t.name == "->":
            left = "(" + left + ")"
        return left + " -> " + _show(t.args[1], names)
    if t.name == "*":
        parts = []
        for arg in t.args:
            arg_p = _prune(arg)
            text = _show(arg_p, names)
            if isinstance(arg_p, _TCon) and arg_p.name in ("->", "*"):
                text = "(" + text + ")"
            parts.append(text)
        return parts[0] + " * " + parts[1]
    if t.name == "list":
        arg_p = _prune(t.args[0])
        text = _show(arg_p, names)
        if isinstance(arg_p, _TCon) and arg_p.name in ("->", "*"):
            text = "(" + text + ")"
        return text + " list"
    return t.name


def _infer_impl(src):
    toks = _lex(src)
    ast = _Parser(toks).parse_top()
    engine = _Infer()
    result = engine.infer(_builtin_env(), ast)
    return _show(result, {})


def infer(src: str) -> str:
    box = {}

    def runner():
        try:
            box["value"] = _infer_impl(src)
        except BaseException as exc:
            box["error"] = exc

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    try:
        sys.setrecursionlimit(max(old_limit, 200000))
        threading.stack_size(512 * 1024 * 1024)
        worker = threading.Thread(target=runner)
        worker.start()
        worker.join()
    finally:
        threading.stack_size(old_stack)
        sys.setrecursionlimit(old_limit)
    if "error" in box:
        raise box["error"]
    return box["value"]
```
