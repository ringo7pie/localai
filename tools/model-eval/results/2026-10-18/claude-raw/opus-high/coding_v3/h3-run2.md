```python
import string
import sys
import threading

_GENERIC = 1 << 62
_MISSING = object()


class _TV:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TC:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _TC("int", ())
_BOOL = _TC("bool", ())


def _arrow(a, b):
    return _TC("->", (a, b))


def _pair(a, b):
    return _TC("*", (a, b))


def _list(a):
    return _TC("list", (a,))


_KEYWORDS = frozenset(
    ["fun", "let", "rec", "in", "if", "then", "else", "true", "false"]
)
_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_'")
_NAME_START = frozenset(string.ascii_lowercase + "_")
_DIGITS = frozenset(string.digits)
_WHITESPACE = frozenset(" \t\n\r")
_SINGLE_SYMBOLS = frozenset("()+*=<,")


def _tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in _WHITESPACE:
            i += 1
            continue
        if ch in _DIGITS:
            j = i
            while j < n and src[j] in _DIGITS:
                j += 1
            toks.append(("INT", src[i:j]))
            i = j
            continue
        if ch in _NAME_START:
            j = i + 1
            while j < n and src[j] in _NAME_CHARS:
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append(("KW", word))
            else:
                toks.append(("NAME", word))
            i = j
            continue
        if ch == "-":
            if i + 1 < n and src[i + 1] == ">":
                toks.append(("SYM", "->"))
                i += 2
            else:
                toks.append(("SYM", "-"))
                i += 1
            continue
        if ch == ":":
            if i + 1 < n and src[i + 1] == ":":
                toks.append(("SYM", "::"))
                i += 2
                continue
            raise SyntaxError("unexpected ':'")
        if ch == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("SYM", "[]"))
                i += 2
                continue
            raise SyntaxError("'[' must be followed by ']'")
        if ch in _SINGLE_SYMBOLS:
            toks.append(("SYM", ch))
            i += 1
            continue
        raise SyntaxError("unexpected character %r" % ch)
    toks.append(("EOF", None))
    return toks


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def advance(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def is_sym(self, value):
        tok = self.toks[self.pos]
        return tok[0] == "SYM" and tok[1] == value

    def is_kw(self, value):
        tok = self.toks[self.pos]
        return tok[0] == "KW" and tok[1] == value

    def expect_sym(self, value):
        if not self.is_sym(value):
            raise SyntaxError("expected %r" % value)
        self.pos += 1

    def expect_kw(self, value):
        if not self.is_kw(value):
            raise SyntaxError("expected %r" % value)
        self.pos += 1

    def parse_names(self):
        names = []
        while self.peek()[0] == "NAME":
            names.append(self.advance()[1])
        return names

    def parse_expr(self):
        if self.is_kw("fun"):
            self.advance()
            params = self.parse_names()
            if not params:
                raise SyntaxError("fun needs at least one parameter")
            self.expect_sym("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if self.is_kw("let"):
            self.advance()
            is_rec = False
            if self.is_kw("rec"):
                self.advance()
                is_rec = True
            tok = self.peek()
            if tok[0] != "NAME":
                raise SyntaxError("expected a name after let")
            self.advance()
            name = tok[1]
            params = self.parse_names()
            if is_rec and not params:
                raise SyntaxError("let rec needs at least one parameter")
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
            cond = self.parse_cmp()
            self.expect_kw("then")
            then_branch = self.parse_expr()
            self.expect_kw("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while True:
            tok = self.peek()
            if tok[0] == "SYM" and (tok[1] == "=" or tok[1] == "<"):
                self.advance()
                right = self.parse_cons()
                left = ("bin", tok[1], left, right)
            else:
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
        while True:
            tok = self.peek()
            if tok[0] == "SYM" and (tok[1] == "+" or tok[1] == "-"):
                self.advance()
                right = self.parse_mul()
                left = ("bin", tok[1], left, right)
            else:
                return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_sym("*"):
            self.advance()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def at_atom_start(self):
        tok = self.peek()
        kind = tok[0]
        if kind == "INT" or kind == "NAME":
            return True
        if kind == "KW":
            return tok[1] == "true" or tok[1] == "false"
        if kind == "SYM":
            return tok[1] == "(" or tok[1] == "[]"
        return False

    def parse_app(self):
        func = self.parse_atom()
        while self.at_atom_start():
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        tok = self.peek()
        kind = tok[0]
        if kind == "INT":
            self.advance()
            return ("int",)
        if kind == "NAME":
            self.advance()
            return ("var", tok[1])
        if kind == "KW" and (tok[1] == "true" or tok[1] == "false"):
            self.advance()
            return ("bool",)
        if kind == "SYM" and tok[1] == "[]":
            self.advance()
            return ("nil",)
        if kind == "SYM" and tok[1] == "(":
            self.advance()
            first = self.parse_expr()
            if self.is_sym(","):
                self.advance()
                second = self.parse_expr()
                self.expect_sym(")")
                return ("tuple", first, second)
            self.expect_sym(")")
            return first
        raise SyntaxError("unexpected token %r" % (tok[1],))


def _prune(typ):
    root = typ
    while type(root) is _TV and root.ref is not None:
        root = root.ref
    while type(typ) is _TV and typ.ref is not None and typ.ref is not root:
        nxt = typ.ref
        typ.ref = root
        typ = nxt
    return root


def _bind(var, typ):
    limit = var.level
    stack = [typ]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if type(node) is _TV:
            if node is var:
                raise TypeError("recursive type")
            if node.level > limit:
                node.level = limit
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node.args)
    var.ref = typ


def _unify(first, second):
    stack = [(first, second)]
    while stack:
        left, right = stack.pop()
        left = _prune(left)
        right = _prune(right)
        if left is right:
            continue
        if type(left) is _TV:
            _bind(left, right)
        elif type(right) is _TV:
            _bind(right, left)
        else:
            if left.name != right.name or len(left.args) != len(right.args):
                raise TypeError(
                    "cannot unify %s with %s" % (left.name, right.name)
                )
            stack.extend(zip(left.args, right.args))


def _generalize(typ, level):
    stack = [typ]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if type(node) is _TV:
            if node.level > level and node.level != _GENERIC:
                node.level = _GENERIC
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node.args)


def _instantiate(typ, level):
    memo = {}

    def go(node):
        node = _prune(node)
        if type(node) is _TV:
            if node.level == _GENERIC:
                key = id(node)
                fresh = memo.get(key)
                if fresh is None:
                    fresh = _TV(level)
                    memo[key] = fresh
                return fresh
            return node
        if not node.args:
            return node
        key = id(node)
        done = memo.get(key)
        if done is not None:
            return done
        copied = _TC(node.name, tuple([go(arg) for arg in node.args]))
        memo[key] = copied
        return copied

    return go(typ)


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    suffix = index // 26
    if suffix:
        return "'" + letter + str(suffix)
    return "'" + letter


def _show(typ):
    names = {}

    def is_compound(node):
        return type(node) is _TC and (node.name == "->" or node.name == "*")

    def go(node):
        node = _prune(node)
        if type(node) is _TV:
            key = id(node)
            name = names.get(key)
            if name is None:
                name = _var_name(len(names))
                names[key] = name
            return name
        if node.name == "list":
            inner = _prune(node.args[0])
            text = go(inner)
            if is_compound(inner):
                text = "(" + text + ")"
            return text + " list"
        if node.name == "->":
            left = _prune(node.args[0])
            left_text = go(left)
            if type(left) is _TC and left.name == "->":
                left_text = "(" + left_text + ")"
            right_text = go(node.args[1])
            return left_text + " -> " + right_text
        if node.name == "*":
            left = _prune(node.args[0])
            left_text = go(left)
            if is_compound(left):
                left_text = "(" + left_text + ")"
            right = _prune(node.args[1])
            right_text = go(right)
            if is_compound(right):
                right_text = "(" + right_text + ")"
            return left_text + " * " + right_text
        return node.name

    return go(typ)


def _run(src):
    parser = _Parser(_tokenize(src))
    ast = parser.parse_expr()
    if parser.peek()[0] != "EOF":
        raise SyntaxError("unexpected token %r" % (parser.peek()[1],))

    env = {}
    var_a = _TV(_GENERIC)
    var_b = _TV(_GENERIC)
    env["fst"] = (_arrow(_pair(var_a, var_b), var_a), True)
    var_a = _TV(_GENERIC)
    var_b = _TV(_GENERIC)
    env["snd"] = (_arrow(_pair(var_a, var_b), var_b), True)
    var_a = _TV(_GENERIC)
    env["hd"] = (_arrow(_list(var_a), var_a), True)
    var_a = _TV(_GENERIC)
    env["tl"] = (_arrow(_list(var_a), _list(var_a)), True)
    var_a = _TV(_GENERIC)
    env["null"] = (_arrow(_list(var_a), _BOOL), True)

    def push(name, entry):
        old = env.get(name, _MISSING)
        env[name] = entry
        return old

    def pop(name, old):
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old

    def inf(node, level):
        kind = node[0]
        if kind == "int":
            return _INT
        if kind == "bool":
            return _BOOL
        if kind == "nil":
            return _list(_TV(level))
        if kind == "var":
            entry = env.get(node[1])
            if entry is None:
                raise NameError("name %r is not defined" % node[1])
            typ, is_poly = entry
            if is_poly:
                return _instantiate(typ, level)
            return typ
        if kind == "app":
            func_type = inf(node[1], level)
            arg_type = inf(node[2], level)
            result = _TV(level)
            _unify(func_type, _arrow(arg_type, result))
            return result
        if kind == "bin":
            op = node[1]
            if op == "+" or op == "-" or op == "*" or op == "<":
                left = inf(node[2], level)
                _unify(left, _INT)
                right = inf(node[3], level)
                _unify(right, _INT)
                return _BOOL if op == "<" else _INT
            if op == "=":
                left = inf(node[2], level)
                right = inf(node[3], level)
                _unify(left, right)
                return _BOOL
            # "::"
            head = inf(node[2], level)
            tail = inf(node[3], level)
            result = _list(head)
            _unify(tail, result)
            return result
        if kind == "tuple":
            first = inf(node[1], level)
            second = inf(node[2], level)
            return _pair(first, second)
        if kind == "if":
            cond = inf(node[1], level)
            _unify(cond, _BOOL)
            then_type = inf(node[2], level)
            else_type = inf(node[3], level)
            _unify(then_type, else_type)
            return then_type
        if kind == "fun":
            params = node[1]
            param_vars = []
            saved = []
            for param in params:
                tv = _TV(level)
                param_vars.append(tv)
                saved.append((param, push(param, (tv, False))))
            result = inf(node[2], level)
            for param, old in reversed(saved):
                pop(param, old)
            for tv in reversed(param_vars):
                result = _arrow(tv, result)
            return result
        if kind == "let":
            name = node[1]
            bound = inf(node[2], level + 1)
            _generalize(bound, level)
            old = push(name, (bound, True))
            result = inf(node[3], level)
            pop(name, old)
            return result
        if kind == "letrec":
            name = node[1]
            self_var = _TV(level + 1)
            old = push(name, (self_var, False))
            fun_type = inf(("fun", node[2], node[3]), level + 1)
            _unify(self_var, fun_type)
            pop(name, old)
            _generalize(self_var, level)
            old = push(name, (self_var, True))
            result = inf(node[4], level)
            pop(name, old)
            return result
        raise SyntaxError("unknown node")

    return _show(inf(ast, 0))


def infer(src: str) -> str:
    box = {}

    def target():
        try:
            box["value"] = _run(src)
        except BaseException as exc:
            box["error"] = exc

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 1000000))
    try:
        old_size = None
        try:
            old_size = threading.stack_size(256 * 1024 * 1024)
        except (ValueError, RuntimeError, OverflowError):
            old_size = None
        try:
            worker = threading.Thread(target=target)
            worker.start()
            worker.join()
        finally:
            if old_size is not None:
                try:
                    threading.stack_size(old_size)
                except (ValueError, RuntimeError, OverflowError):
                    pass
    finally:
        sys.setrecursionlimit(old_limit)
    if "error" in box:
        raise box["error"]
    return box["value"]
```
