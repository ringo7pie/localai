```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 1 << 60


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


_INT = _TCon("int", ())
_BOOL = _TCon("bool", ())


def _fn(a, b):
    return _TCon("fn", (a, b))


def _lst(a):
    return _TCon("list", (a,))


def _tup(a, b):
    return _TCon("tuple", (a, b))


# ---------------------------------------------------------------- lexer

def _is_name_start(ch):
    return ("a" <= ch <= "z") or ch == "_"


def _is_name_char(ch):
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch == "_" or ch == "'"


def _lex(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n":
            i += 1
            continue
        if "0" <= ch <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            toks.append(("int", src[i:j]))
            i = j
        elif _is_name_start(ch):
            j = i + 1
            while j < n and _is_name_char(src[j]):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append(("kw", word))
            else:
                toks.append(("name", word))
            i = j
        elif ch == "-":
            if i + 1 < n and src[i + 1] == ">":
                toks.append(("sym", "->"))
                i += 2
            else:
                toks.append(("sym", "-"))
                i += 1
        elif ch == ":":
            if i + 1 < n and src[i + 1] == ":":
                toks.append(("sym", "::"))
                i += 2
            else:
                raise SyntaxError("unexpected ':'")
        elif ch == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("sym", "[]"))
                i += 2
            else:
                raise SyntaxError("'[' must be followed by ']'")
        elif ch in "(),+*=<":
            toks.append(("sym", ch))
            i += 1
        else:
            raise SyntaxError("unexpected character %r" % ch)
    toks.append(("eof", None))
    return toks


# ---------------------------------------------------------------- parser

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

    def is_sym(self, sym):
        kind, val = self.toks[self.pos]
        return kind == "sym" and val == sym

    def is_kw(self, word):
        kind, val = self.toks[self.pos]
        return kind == "kw" and val == word

    def expect_sym(self, sym):
        if not self.is_sym(sym):
            raise SyntaxError("expected %r" % sym)
        self.pos += 1

    def expect_kw(self, word):
        if not self.is_kw(word):
            raise SyntaxError("expected %r" % word)
        self.pos += 1

    def expect_name(self):
        kind, val = self.toks[self.pos]
        if kind != "name":
            raise SyntaxError("expected a name")
        self.pos += 1
        return val

    def parse_program(self):
        expr = self.parse_top()
        if self.peek()[0] != "eof":
            raise SyntaxError("unexpected token %r" % (self.peek()[1],))
        return expr

    @staticmethod
    def make_fun(params, body):
        result = body
        for param in reversed(params):
            result = ("fun", param, result)
        return result

    def parse_params(self):
        params = []
        while self.peek()[0] == "name":
            params.append(self.advance()[1])
        return params

    def parse_top(self):
        if self.is_kw("fun"):
            self.advance()
            params = self.parse_params()
            if not params:
                raise SyntaxError("fun needs at least one parameter")
            self.expect_sym("->")
            body = self.parse_top()
            return self.make_fun(params, body)
        if self.is_kw("let"):
            self.advance()
            is_rec = False
            if self.is_kw("rec"):
                self.advance()
                is_rec = True
            name = self.expect_name()
            params = self.parse_params()
            if is_rec and not params:
                raise SyntaxError("let rec needs at least one parameter")
            self.expect_sym("=")
            bound = self.parse_top()
            self.expect_kw("in")
            body = self.parse_top()
            if params:
                bound = self.make_fun(params, bound)
            return ("letrec" if is_rec else "let", name, bound, body)
        if self.is_kw("if"):
            self.advance()
            cond = self.parse_top()
            self.expect_kw("then")
            then_branch = self.parse_top()
            self.expect_kw("else")
            else_branch = self.parse_top()
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
        for idx in range(len(items) - 2, -1, -1):
            result = ("bin", "::", items[idx], result)
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
        kind, val = self.peek()
        if kind == "int" or kind == "name":
            return True
        if kind == "kw" and val in ("true", "false"):
            return True
        if kind == "sym" and val in ("[]", "("):
            return True
        return False

    def parse_app(self):
        func = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        kind, val = self.peek()
        if kind == "int":
            self.advance()
            return ("int",)
        if kind == "name":
            self.advance()
            return ("var", val)
        if kind == "kw" and val in ("true", "false"):
            self.advance()
            return ("bool",)
        if kind == "sym" and val == "[]":
            self.advance()
            return ("nil",)
        if kind == "sym" and val == "(":
            self.advance()
            first = self.parse_top()
            if self.is_sym(","):
                self.advance()
                second = self.parse_top()
                self.expect_sym(")")
                return ("tuple", first, second)
            self.expect_sym(")")
            return first
        raise SyntaxError("unexpected token %r" % (val,))


# ---------------------------------------------------------------- types

def _prune(t):
    root = t
    while isinstance(root, _TVar) and root.ref is not None:
        root = root.ref
    while isinstance(t, _TVar) and t.ref is not None:
        nxt = t.ref
        t.ref = root
        t = nxt
    return root


def _occurs_adjust(var, t):
    stack = [t]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if isinstance(node, _TVar):
            if node is var:
                raise TypeError("recursive type")
            if node.level > var.level:
                node.level = var.level
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node.args)


def _unify(a, b):
    stack = [(a, b)]
    while stack:
        left, right = stack.pop()
        left = _prune(left)
        right = _prune(right)
        if left is right:
            continue
        if isinstance(left, _TVar):
            _occurs_adjust(left, right)
            left.ref = right
        elif isinstance(right, _TVar):
            _occurs_adjust(right, left)
            right.ref = left
        else:
            if left.name != right.name or len(left.args) != len(right.args):
                raise TypeError("type mismatch")
            for idx in range(len(left.args)):
                stack.append((left.args[idx], right.args[idx]))


def _generalize(t, level):
    stack = [t]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if isinstance(node, _TVar):
            if node.level > level:
                node.level = _GENERIC
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(node.args)


class _Inferer:
    def __init__(self):
        self.level = 1
        self.env = {}
        a = _TVar(_GENERIC)
        b = _TVar(_GENERIC)
        self.env["fst"] = (True, _fn(_tup(a, b), a))
        a = _TVar(_GENERIC)
        b = _TVar(_GENERIC)
        self.env["snd"] = (True, _fn(_tup(a, b), b))
        a = _TVar(_GENERIC)
        self.env["hd"] = (True, _fn(_lst(a), a))
        a = _TVar(_GENERIC)
        self.env["tl"] = (True, _fn(_lst(a), _lst(a)))
        a = _TVar(_GENERIC)
        self.env["null"] = (True, _fn(_lst(a), _BOOL))

    def fresh(self):
        return _TVar(self.level)

    def instantiate(self, t):
        memo = {}
        return self._inst(t, memo)

    def _inst(self, t, memo):
        t = _prune(t)
        key = id(t)
        if key in memo:
            return memo[key]
        if isinstance(t, _TVar):
            if t.level == _GENERIC:
                new_var = _TVar(self.level)
                memo[key] = new_var
                return new_var
            return t
        if not t.args:
            return t
        new_args = []
        changed = False
        for arg in t.args:
            new_arg = self._inst(arg, memo)
            if new_arg is not arg:
                changed = True
            new_args.append(new_arg)
        result = _TCon(t.name, tuple(new_args)) if changed else t
        memo[key] = result
        return result

    def bind(self, name, entry):
        old = self.env.get(name)
        self.env[name] = entry
        return old

    def unbind(self, name, old):
        if old is None:
            del self.env[name]
        else:
            self.env[name] = old

    def infer(self, expr):
        tag = expr[0]
        if tag == "int":
            return _INT
        if tag == "bool":
            return _BOOL
        if tag == "nil":
            return _lst(self.fresh())
        if tag == "var":
            entry = self.env.get(expr[1])
            if entry is None:
                raise NameError("undefined name %r" % expr[1])
            is_poly, t = entry
            if is_poly:
                return self.instantiate(t)
            return t
        if tag == "tuple":
            first = self.infer(expr[1])
            second = self.infer(expr[2])
            return _tup(first, second)
        if tag == "app":
            func_t = self.infer(expr[1])
            arg_t = self.infer(expr[2])
            res_t = self.fresh()
            _unify(func_t, _fn(arg_t, res_t))
            return res_t
        if tag == "bin":
            op = expr[1]
            left_t = self.infer(expr[2])
            right_t = self.infer(expr[3])
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
            # '::'
            list_t = _lst(left_t)
            _unify(right_t, list_t)
            return list_t
        if tag == "fun":
            param = expr[1]
            param_t = self.fresh()
            old = self.bind(param, (False, param_t))
            body_t = self.infer(expr[2])
            self.unbind(param, old)
            return _fn(param_t, body_t)
        if tag == "let":
            name = expr[1]
            self.level += 1
            bound_t = self.infer(expr[2])
            self.level -= 1
            _generalize(bound_t, self.level)
            old = self.bind(name, (True, bound_t))
            body_t = self.infer(expr[3])
            self.unbind(name, old)
            return body_t
        if tag == "letrec":
            name = expr[1]
            self.level += 1
            self_t = self.fresh()
            old = self.bind(name, (False, self_t))
            bound_t = self.infer(expr[2])
            _unify(self_t, bound_t)
            self.unbind(name, old)
            self.level -= 1
            _generalize(self_t, self.level)
            old = self.bind(name, (True, self_t))
            body_t = self.infer(expr[3])
            self.unbind(name, old)
            return body_t
        if tag == "if":
            cond_t = self.infer(expr[1])
            _unify(cond_t, _BOOL)
            then_t = self.infer(expr[2])
            else_t = self.infer(expr[3])
            _unify(then_t, else_t)
            return then_t
        raise SyntaxError("unknown node")


# ---------------------------------------------------------------- printing

def _var_name(index):
    letter = chr(ord("a") + index % 26)
    suffix = index // 26
    if suffix:
        return "'" + letter + str(suffix)
    return "'" + letter


def _needs_paren(t):
    return isinstance(t, _TCon) and t.name in ("fn", "tuple")


def _format(t, names):
    t = _prune(t)
    if isinstance(t, _TVar):
        key = id(t)
        if key not in names:
            names[key] = _var_name(len(names))
        return names[key]
    if t.name == "int" or t.name == "bool":
        return t.name
    if t.name == "list":
        inner = _prune(t.args[0])
        text = _format(inner, names)
        if _needs_paren(inner):
            text = "(" + text + ")"
        return text + " list"
    if t.name == "tuple":
        parts = []
        for arg in t.args:
            arg = _prune(arg)
            text = _format(arg, names)
            if _needs_paren(arg):
                text = "(" + text + ")"
            parts.append(text)
        return parts[0] + " * " + parts[1]
    # fn
    left = _prune(t.args[0])
    left_text = _format(left, names)
    if isinstance(left, _TCon) and left.name == "fn":
        left_text = "(" + left_text + ")"
    right_text = _format(t.args[1], names)
    return left_text + " -> " + right_text


def _infer_impl(src):
    toks = _lex(src)
    ast = _Parser(toks).parse_program()
    inferer = _Inferer()
    result_t = inferer.infer(ast)
    return _format(result_t, {})


def infer(src: str) -> str:
    outcome = {}

    def run():
        try:
            outcome["value"] = _infer_impl(src)
        except BaseException as exc:  # re-raised in the caller's thread
            outcome["error"] = exc

    old_limit = sys.getrecursionlimit()
    if old_limit < 1000000:
        sys.setrecursionlimit(1000000)
    old_stack = threading.stack_size()
    try:
        try:
            threading.stack_size(512 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        worker = threading.Thread(target=run)
        worker.start()
        worker.join()
    finally:
        try:
            threading.stack_size(old_stack)
        except (ValueError, RuntimeError):
            pass
        sys.setrecursionlimit(old_limit)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
