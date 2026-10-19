```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 1 << 60


def _tokenize(src):
    tokens = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch in " \t\n\r":
            pos += 1
            continue
        if ch.isascii() and ch.isdigit():
            start = pos
            while pos < length and src[pos].isascii() and src[pos].isdigit():
                pos += 1
            tokens.append(("int", int(src[start:pos])))
            continue
        if ("a" <= ch <= "z") or ch == "_":
            start = pos
            pos += 1
            while pos < length:
                c2 = src[pos]
                if c2.isascii() and (c2.isalnum() or c2 == "_" or c2 == "'"):
                    pos += 1
                else:
                    break
            word = src[start:pos]
            if word in _KEYWORDS:
                tokens.append(("kw", word))
            else:
                tokens.append(("name", word))
            continue
        if ch == "-":
            if pos + 1 < length and src[pos + 1] == ">":
                tokens.append(("sym", "->"))
                pos += 2
            else:
                tokens.append(("sym", "-"))
                pos += 1
            continue
        if ch == ":":
            if pos + 1 < length and src[pos + 1] == ":":
                tokens.append(("sym", "::"))
                pos += 2
                continue
            raise SyntaxError("unexpected ':'")
        if ch == "[":
            if pos + 1 < length and src[pos + 1] == "]":
                tokens.append(("nil", "[]"))
                pos += 2
                continue
            raise SyntaxError("expected ']'")
        if ch in "(),+*=<":
            tokens.append(("sym", ch))
            pos += 1
            continue
        raise SyntaxError("unexpected character %r" % ch)
    tokens.append(("eof", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok[0] != "eof":
            self.pos += 1
        return tok

    def is_sym(self, sym):
        tok = self.tokens[self.pos]
        return tok[0] == "sym" and tok[1] == sym

    def is_kw(self, kw):
        tok = self.tokens[self.pos]
        return tok[0] == "kw" and tok[1] == kw

    def expect_sym(self, sym):
        if not self.is_sym(sym):
            raise SyntaxError("expected %r" % sym)
        self.advance()

    def expect_kw(self, kw):
        if not self.is_kw(kw):
            raise SyntaxError("expected %r" % kw)
        self.advance()

    def expect_name(self):
        tok = self.peek()
        if tok[0] != "name":
            raise SyntaxError("expected name")
        self.advance()
        return tok[1]

    def parse_program(self):
        expr = self.parse_expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("unexpected token")
        return expr

    def parse_expr(self):
        if self.is_kw("fun"):
            self.advance()
            params = []
            while self.peek()[0] == "name":
                params.append(self.advance()[1])
            if not params:
                raise SyntaxError("fun needs parameters")
            self.expect_sym("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if self.is_kw("let"):
            self.advance()
            is_rec = False
            if self.is_kw("rec"):
                self.advance()
                is_rec = True
            name = self.expect_name()
            params = []
            while self.peek()[0] == "name":
                params.append(self.advance()[1])
            if is_rec and not params:
                raise SyntaxError("let rec needs parameters")
            self.expect_sym("=")
            bound = self.parse_expr()
            self.expect_kw("in")
            body = self.parse_expr()
            if is_rec:
                return ("letrec", name, params, bound, body)
            if params:
                bound = ("fun", params, bound)
            return ("let", name, bound, body)
        if self.is_kw("if"):
            self.advance()
            cond = self.parse_expr()
            self.expect_kw("then")
            then_e = self.parse_expr()
            self.expect_kw("else")
            else_e = self.parse_expr()
            return ("if", cond, then_e, else_e)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.is_sym("=") or self.is_sym("<"):
            op = self.advance()[1]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        left = self.parse_add()
        if self.is_sym("::"):
            self.advance()
            right = self.parse_cons()
            return ("bin", "::", left, right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.is_sym("+") or self.is_sym("-"):
            op = self.advance()[1]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_sym("*"):
            self.advance()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def starts_atom(self):
        tok = self.peek()
        kind = tok[0]
        if kind in ("int", "name", "nil"):
            return True
        if kind == "kw" and tok[1] in ("true", "false"):
            return True
        if kind == "sym" and tok[1] == "(":
            return True
        return False

    def parse_app(self):
        func = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        tok = self.peek()
        kind = tok[0]
        if kind == "int":
            self.advance()
            return ("int", tok[1])
        if kind == "name":
            self.advance()
            return ("var", tok[1])
        if kind == "nil":
            self.advance()
            return ("nil",)
        if kind == "kw" and tok[1] in ("true", "false"):
            self.advance()
            return ("bool", tok[1] == "true")
        if kind == "sym" and tok[1] == "(":
            self.advance()
            first = self.parse_expr()
            if self.is_sym(","):
                self.advance()
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

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _TCon("int", [])
_BOOL = _TCon("bool", [])


def _arrow(a, b):
    return _TCon("->", [a, b])


def _list(a):
    return _TCon("list", [a])


def _tuple(a, b):
    return _TCon("*", [a, b])


def _prune(t):
    root = t
    while isinstance(root, _TVar) and root.ref is not None:
        root = root.ref
    while isinstance(t, _TVar) and t.ref is not None and t.ref is not root:
        nxt = t.ref
        t.ref = root
        t = nxt
    return root


class _Inferer:
    def __init__(self):
        self.level = 0
        self.env = {}
        g1 = _TVar(_GENERIC)
        g2 = _TVar(_GENERIC)
        self.env["fst"] = _arrow(_tuple(g1, g2), g1)
        g1 = _TVar(_GENERIC)
        g2 = _TVar(_GENERIC)
        self.env["snd"] = _arrow(_tuple(g1, g2), g2)
        g1 = _TVar(_GENERIC)
        self.env["hd"] = _arrow(_list(g1), g1)
        g1 = _TVar(_GENERIC)
        self.env["tl"] = _arrow(_list(g1), _list(g1))
        g1 = _TVar(_GENERIC)
        self.env["null"] = _arrow(_list(g1), _BOOL)

    def new_var(self):
        return _TVar(self.level)

    def occurs_adjust(self, var, t):
        t = _prune(t)
        if t is var:
            raise TypeError("recursive type")
        if isinstance(t, _TVar):
            if t.level > var.level:
                t.level = var.level
            return
        for arg in t.args:
            self.occurs_adjust(var, arg)

    def unify(self, a, b):
        a = _prune(a)
        b = _prune(b)
        if a is b:
            return
        if isinstance(a, _TVar):
            self.occurs_adjust(a, b)
            a.ref = b
            return
        if isinstance(b, _TVar):
            self.occurs_adjust(b, a)
            b.ref = a
            return
        if a.name != b.name or len(a.args) != len(b.args):
            raise TypeError("type mismatch")
        for x, y in zip(a.args, b.args):
            self.unify(x, y)

    def generalize(self, t):
        t = _prune(t)
        if isinstance(t, _TVar):
            if t.level > self.level and t.level != _GENERIC:
                t.level = _GENERIC
            return
        for arg in t.args:
            self.generalize(arg)

    def instantiate(self, t):
        mapping = {}

        def copy(ty):
            ty = _prune(ty)
            if isinstance(ty, _TVar):
                if ty.level == _GENERIC:
                    key = id(ty)
                    nv = mapping.get(key)
                    if nv is None:
                        nv = self.new_var()
                        mapping[key] = nv
                    return nv
                return ty
            if not ty.args:
                return ty
            return _TCon(ty.name, [copy(arg) for arg in ty.args])

        return copy(t)

    def bind(self, name, t):
        old = self.env.get(name, None)
        had = name in self.env
        self.env[name] = t
        return (name, had, old)

    def restore(self, saved):
        name, had, old = saved
        if had:
            self.env[name] = old
        else:
            del self.env[name]

    def infer_fun(self, params, body):
        param_types = []
        saved = []
        for param in params:
            tv = self.new_var()
            param_types.append(tv)
            saved.append(self.bind(param, tv))
        result = self.infer(body)
        for item in reversed(saved):
            self.restore(item)
        for tv in reversed(param_types):
            result = _arrow(tv, result)
        return result

    def infer(self, node):
        kind = node[0]
        if kind == "int":
            return _INT
        if kind == "bool":
            return _BOOL
        if kind == "nil":
            return _list(self.new_var())
        if kind == "var":
            name = node[1]
            if name not in self.env:
                raise NameError("undefined name: %s" % name)
            return self.instantiate(self.env[name])
        if kind == "tuple":
            first = self.infer(node[1])
            second = self.infer(node[2])
            return _tuple(first, second)
        if kind == "bin":
            op = node[1]
            left = self.infer(node[2])
            right = self.infer(node[3])
            if op in ("+", "-", "*"):
                self.unify(left, _INT)
                self.unify(right, _INT)
                return _INT
            if op == "<":
                self.unify(left, _INT)
                self.unify(right, _INT)
                return _BOOL
            if op == "=":
                self.unify(left, right)
                return _BOOL
            # "::"
            self.unify(right, _list(left))
            return right
        if kind == "app":
            func = self.infer(node[1])
            arg = self.infer(node[2])
            result = self.new_var()
            self.unify(func, _arrow(arg, result))
            return result
        if kind == "fun":
            return self.infer_fun(node[1], node[2])
        if kind == "if":
            cond = self.infer(node[1])
            self.unify(cond, _BOOL)
            then_t = self.infer(node[2])
            else_t = self.infer(node[3])
            self.unify(then_t, else_t)
            return then_t
        if kind == "let":
            name = node[1]
            self.level += 1
            bound = self.infer(node[2])
            self.level -= 1
            self.generalize(bound)
            saved = self.bind(name, bound)
            result = self.infer(node[3])
            self.restore(saved)
            return result
        if kind == "letrec":
            name, params, bound_body, body = node[1], node[2], node[3], node[4]
            self.level += 1
            self_var = self.new_var()
            saved = self.bind(name, self_var)
            fun_t = self.infer_fun(params, bound_body)
            self.unify(self_var, fun_t)
            self.restore(saved)
            self.level -= 1
            self.generalize(fun_t)
            saved = self.bind(name, fun_t)
            result = self.infer(body)
            self.restore(saved)
            return result
        raise SyntaxError("unknown node")


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    if index >= 26:
        return "'" + letter + str(index // 26)
    return "'" + letter


def _type_to_str(t):
    names = {}

    def render(ty, ctx):
        ty = _prune(ty)
        if isinstance(ty, _TVar):
            key = id(ty)
            if key not in names:
                names[key] = _var_name(len(names))
            return names[key]
        if ty.name == "int" or ty.name == "bool":
            return ty.name
        if ty.name == "list":
            return render(ty.args[0], 2) + " list"
        if ty.name == "*":
            left = render(ty.args[0], 2)
            right = render(ty.args[1], 2)
            text = left + " * " + right
            if ctx >= 2:
                return "(" + text + ")"
            return text
        # "->"
        left = render(ty.args[0], 1)
        right = render(ty.args[1], 0)
        text = left + " -> " + right
        if ctx >= 1:
            return "(" + text + ")"
        return text

    return render(t, 0)


def _infer_impl(src):
    tokens = _tokenize(src)
    ast = _Parser(tokens).parse_program()
    inferer = _Inferer()
    result = inferer.infer(ast)
    return _type_to_str(result)


def infer(src: str) -> str:
    box = {}

    def worker():
        try:
            box["result"] = _infer_impl(src)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    try:
        sys.setrecursionlimit(max(old_limit, 1000000))
        try:
            threading.stack_size(512 * 1024 * 1024)
        except (ValueError, RuntimeError):
            try:
                threading.stack_size(128 * 1024 * 1024)
            except (ValueError, RuntimeError):
                pass
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    finally:
        try:
            threading.stack_size(old_stack)
        except (ValueError, RuntimeError):
            pass
        sys.setrecursionlimit(old_limit)
    if "error" in box:
        raise box["error"]
    return box["result"]
```
