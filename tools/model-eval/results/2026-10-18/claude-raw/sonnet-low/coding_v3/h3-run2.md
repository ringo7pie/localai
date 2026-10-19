```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 10 ** 9


def _lex(src):
    tokens = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch in " \t\n":
            pos += 1
        elif "0" <= ch <= "9":
            end = pos
            while end < length and "0" <= src[end] <= "9":
                end += 1
            tokens.append(("int", src[pos:end]))
            pos = end
        elif ("a" <= ch <= "z") or ch == "_":
            end = pos + 1
            while end < length and (("a" <= src[end] <= "z") or ("A" <= src[end] <= "Z")
                                    or ("0" <= src[end] <= "9") or src[end] in "_'"):
                end += 1
            word = src[pos:end]
            tokens.append(("kw" if word in _KEYWORDS else "name", word))
            pos = end
        elif src.startswith("->", pos):
            tokens.append(("sym", "->"))
            pos += 2
        elif src.startswith("::", pos):
            tokens.append(("sym", "::"))
            pos += 2
        elif ch in "(),+-*=<[]":
            tokens.append(("sym", ch))
            pos += 1
        else:
            raise SyntaxError("bad character")
    tokens.append(("eof", ""))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def is_sym(self, value):
        return self.tokens[self.pos] == ("sym", value)

    def is_kw(self, value):
        return self.tokens[self.pos] == ("kw", value)

    def expect_sym(self, value):
        if not self.is_sym(value):
            raise SyntaxError("expected " + value)
        self.pos += 1

    def expect_kw(self, value):
        if not self.is_kw(value):
            raise SyntaxError("expected " + value)
        self.pos += 1

    def expect_name(self):
        token = self.peek()
        if token[0] != "name":
            raise SyntaxError("expected name")
        self.pos += 1
        return token[1]

    def params(self):
        names = []
        while self.peek()[0] == "name":
            names.append(self.advance()[1])
        return names

    def parse_expr(self):
        kind, value = self.peek()
        if kind == "kw":
            if value == "fun":
                self.advance()
                names = self.params()
                if not names:
                    raise SyntaxError("fun needs params")
                self.expect_sym("->")
                body = self.parse_expr()
                return ("fun", names, body)
            if value == "let":
                self.advance()
                is_rec = False
                if self.is_kw("rec"):
                    self.advance()
                    is_rec = True
                name = self.expect_name()
                names = self.params()
                if is_rec and not names:
                    raise SyntaxError("let rec needs params")
                self.expect_sym("=")
                bound = self.parse_expr()
                self.expect_kw("in")
                body = self.parse_expr()
                return ("letrec" if is_rec else "let", name, names, bound, body)
            if value == "if":
                self.advance()
                cond = self.parse_expr()
                self.expect_kw("then")
                then_branch = self.parse_expr()
                self.expect_kw("else")
                else_branch = self.parse_expr()
                return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.is_sym("=") or self.is_sym("<"):
            op = self.advance()[1]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        items = [self.parse_add()]
        while self.is_sym("::"):
            self.advance()
            items.append(self.parse_add())
        result = items[-1]
        for index in range(len(items) - 2, -1, -1):
            result = ("bin", "::", items[index], result)
        return result

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
        kind, value = self.peek()
        if kind in ("int", "name"):
            return True
        if kind == "kw":
            return value in ("true", "false")
        return kind == "sym" and value in ("(", "[")

    def parse_app(self):
        left = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            left = ("app", left, arg)
        return left

    def parse_atom(self):
        kind, value = self.advance()
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
                self.advance()
                second = self.parse_expr()
                self.expect_sym(")")
                return ("tuple", first, second)
            self.expect_sym(")")
            return first
        raise SyntaxError("unexpected token")


class _Var:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _Con:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = args


_INT = _Con("int")
_BOOL = _Con("bool")


def _prune(typ):
    while isinstance(typ, _Var) and typ.ref is not None:
        typ = typ.ref
    return typ


class _Inferer:
    def __init__(self):
        self.level = 0

    def fresh(self):
        return _Var(self.level)

    def occurs_adjust(self, var, typ):
        typ = _prune(typ)
        if isinstance(typ, _Var):
            if typ is var:
                raise TypeError("occurs check")
            if typ.level > var.level:
                typ.level = var.level
            return
        for arg in typ.args:
            self.occurs_adjust(var, arg)

    def unify(self, left, right):
        left = _prune(left)
        right = _prune(right)
        if left is right:
            return
        if isinstance(left, _Var):
            self.occurs_adjust(left, right)
            left.ref = right
            return
        if isinstance(right, _Var):
            self.occurs_adjust(right, left)
            right.ref = left
            return
        if left.name != right.name or len(left.args) != len(right.args):
            raise TypeError("mismatch")
        for first, second in zip(left.args, right.args):
            self.unify(first, second)

    def generalize(self, typ, seen):
        typ = _prune(typ)
        if id(typ) in seen:
            return
        seen.add(id(typ))
        if isinstance(typ, _Var):
            if typ.level > self.level:
                typ.level = _GENERIC
            return
        for arg in typ.args:
            self.generalize(arg, seen)

    def instantiate(self, typ, mapping):
        typ = _prune(typ)
        if isinstance(typ, _Var):
            if typ.level == _GENERIC:
                if id(typ) not in mapping:
                    mapping[id(typ)] = self.fresh()
                return mapping[id(typ)]
            return typ
        if id(typ) in mapping:
            return mapping[id(typ)]
        if not typ.args:
            return typ
        result = _Con(typ.name, tuple(self.instantiate(arg, mapping) for arg in typ.args))
        mapping[id(typ)] = result
        return result

    def lookup(self, env, name):
        while env is not None:
            if env[0] == name:
                return self.instantiate(env[1], {})
            env = env[2]
        builtin = self.builtin(name)
        if builtin is None:
            raise NameError(name)
        return builtin

    def builtin(self, name):
        if name == "fst":
            a, b = self.fresh(), self.fresh()
            return _Con("fun", (_Con("tuple", (a, b)), a))
        if name == "snd":
            a, b = self.fresh(), self.fresh()
            return _Con("fun", (_Con("tuple", (a, b)), b))
        if name == "hd":
            a = self.fresh()
            return _Con("fun", (_Con("list", (a,)), a))
        if name == "tl":
            a = self.fresh()
            return _Con("fun", (_Con("list", (a,)), _Con("list", (a,))))
        if name == "null":
            a = self.fresh()
            return _Con("fun", (_Con("list", (a,)), _BOOL))
        return None

    def infer_fun(self, names, body_fn, env):
        vars_ = []
        for name in names:
            var = self.fresh()
            vars_.append(var)
            env = (name, var, env)
        result = body_fn(env)
        for var in reversed(vars_):
            result = _Con("fun", (var, result))
        return result

    def infer(self, node, env):
        tag = node[0]
        if tag == "int":
            return _INT
        if tag == "bool":
            return _BOOL
        if tag == "nil":
            return _Con("list", (self.fresh(),))
        if tag == "var":
            return self.lookup(env, node[1])
        if tag == "tuple":
            first = self.infer(node[1], env)
            second = self.infer(node[2], env)
            return _Con("tuple", (first, second))
        if tag == "app":
            func = self.infer(node[1], env)
            arg = self.infer(node[2], env)
            result = self.fresh()
            self.unify(func, _Con("fun", (arg, result)))
            return result
        if tag == "bin":
            op = node[1]
            left = self.infer(node[2], env)
            right = self.infer(node[3], env)
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
            self.unify(right, _Con("list", (left,)))
            return right
        if tag == "if":
            cond = self.infer(node[1], env)
            self.unify(cond, _BOOL)
            then_type = self.infer(node[2], env)
            else_type = self.infer(node[3], env)
            self.unify(then_type, else_type)
            return then_type
        if tag == "fun":
            return self.infer_fun(node[1], lambda inner: self.infer(node[2], inner), env)
        if tag == "let":
            _, name, names, bound, body = node
            self.level += 1
            if names:
                typ = self.infer_fun(names, lambda inner: self.infer(bound, inner), env)
            else:
                typ = self.infer(bound, env)
            self.level -= 1
            self.generalize(typ, set())
            return self.infer(body, (name, typ, env))
        if tag == "letrec":
            _, name, names, bound, body = node
            self.level += 1
            func_var = self.fresh()
            inner_env = (name, func_var, env)
            typ = self.infer_fun(names, lambda inner: self.infer(bound, inner), inner_env)
            self.unify(func_var, typ)
            self.level -= 1
            self.generalize(func_var, set())
            return self.infer(body, (name, func_var, env))
        raise SyntaxError("unknown node")


def _letter(index):
    letter = chr(97 + index % 26)
    return "'" + letter + (str(index // 26) if index >= 26 else "")


def _show(typ, context, names):
    typ = _prune(typ)
    if isinstance(typ, _Var):
        if id(typ) not in names:
            names[id(typ)] = _letter(len(names))
        return names[id(typ)]
    if typ.name in ("int", "bool"):
        return typ.name
    if typ.name == "list":
        return _show(typ.args[0], 3, names) + " list"
    if typ.name == "tuple":
        text = _show(typ.args[0], 2, names) + " * " + _show(typ.args[1], 2, names)
        return "(" + text + ")" if context >= 2 else text
    text = _show(typ.args[0], 1, names) + " -> " + _show(typ.args[1], 0, names)
    return "(" + text + ")" if context >= 1 else text


def _run(src):
    tokens = _lex(src)
    parser = _Parser(tokens)
    tree = parser.parse_expr()
    if parser.peek()[0] != "eof":
        raise SyntaxError("trailing tokens")
    inferer = _Inferer()
    typ = inferer.infer(tree, None)
    return _show(typ, 0, {})


def infer(src: str) -> str:
    outcome = {}

    def target():
        try:
            outcome["value"] = _run(src)
        except BaseException as error:
            outcome["error"] = error

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    sys.setrecursionlimit(1000000)
    try:
        threading.stack_size(512 * 1024 * 1024)
        worker = threading.Thread(target=target)
        worker.start()
        worker.join()
    finally:
        threading.stack_size(old_stack)
        sys.setrecursionlimit(old_limit)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
