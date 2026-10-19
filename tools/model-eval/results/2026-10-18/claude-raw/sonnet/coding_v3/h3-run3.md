```python
import sys

_KEYWORDS = frozenset(("fun", "let", "rec", "in", "if", "then", "else", "true", "false"))
_NAME_START = frozenset("abcdefghijklmnopqrstuvwxyz_")
_NAME_REST = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'")
_DIGITS = frozenset("0123456789")
_SPACES = frozenset(" \t\n\r")
_SYMBOLS = frozenset("()[],+-*=<")
_ATOM_START = frozenset(("int", "name", "true", "false", "(", "["))
_GENERIC = 1 << 60
_RECURSION_LIMIT = 1000000
_MISSING = object()


# ---------------------------------------------------------------- types

class _Var:
    __slots__ = ("link", "level")

    def __init__(self, level):
        self.link = None
        self.level = level


class _Ty:
    __slots__ = ("kind", "args")

    def __init__(self, kind, args):
        self.kind = kind
        self.args = args


_INT = _Ty("int", ())
_BOOL = _Ty("bool", ())


def _fn(arg, result):
    return _Ty("fun", (arg, result))


def _lst(item):
    return _Ty("list", (item,))


def _tup(first, second):
    return _Ty("tuple", (first, second))


def _prune(ty):
    if type(ty) is not _Var or ty.link is None:
        return ty
    root = ty
    while type(root) is _Var and root.link is not None:
        root = root.link
    while type(ty) is _Var and ty.link is not None:
        following = ty.link
        ty.link = root
        ty = following
    return root


def _bind(var, ty):
    level = var.level
    stack = [ty]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if cur is var:
            raise TypeError("occurs check")
        if type(cur) is _Var:
            if cur.level > level:
                cur.level = level
        elif cur.args:
            if cur not in seen:
                seen.add(cur)
                stack.extend(cur.args)
    var.link = ty


def _unify(left, right):
    stack = [(left, right)]
    done = set()
    while stack:
        first, second = stack.pop()
        first = _prune(first)
        second = _prune(second)
        if first is second:
            continue
        if type(first) is _Var:
            _bind(first, second)
        elif type(second) is _Var:
            _bind(second, first)
        else:
            if first.kind != second.kind:
                raise TypeError("type mismatch")
            args_first = first.args
            if not args_first:
                continue
            key = (first, second)
            if key in done:
                continue
            done.add(key)
            args_second = second.args
            for index in range(len(args_first)):
                stack.append((args_first[index], args_second[index]))


def _generalize(ty, level):
    stack = [ty]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _Var:
            if cur.level > level:
                cur.level = _GENERIC
        elif cur.args and cur not in seen:
            seen.add(cur)
            stack.extend(cur.args)


def _copy(node, level, memo):
    node = _prune(node)
    if type(node) is _Var:
        if node.level != _GENERIC:
            return node
        fresh = memo.get(node)
        if fresh is None:
            fresh = _Var(level)
            memo[node] = fresh
        return fresh
    args = node.args
    if not args:
        return node
    cached = memo.get(node)
    if cached is not None:
        return cached
    new_args = []
    changed = False
    for arg in args:
        new_arg = _copy(arg, level, memo)
        if new_arg is not arg:
            changed = True
        new_args.append(new_arg)
    result = _Ty(node.kind, tuple(new_args)) if changed else node
    memo[node] = result
    return result


def _instantiate(scheme, level):
    return _copy(scheme, level, {})


def _var_name(index):
    base = "abcdefghijklmnopqrstuvwxyz"[index % 26]
    suffix = index // 26
    return "'" + base + (str(suffix) if suffix else "")


def _show(ty):
    names = {}
    out = []
    # context: 0 = top level or right side of an arrow, 1 = left side of an arrow,
    #          2 = operand of '*', 3 = operand of 'list'
    stack = [(ty, 0)]
    while stack:
        item = stack.pop()
        if type(item) is str:
            out.append(item)
            continue
        node, context = item
        node = _prune(node)
        if type(node) is _Var:
            name = names.get(node)
            if name is None:
                name = _var_name(len(names))
                names[node] = name
            out.append(name)
            continue
        kind = node.kind
        if kind == "int":
            out.append("int")
        elif kind == "bool":
            out.append("bool")
        elif kind == "fun":
            if context >= 1:
                out.append("(")
                stack.append(")")
            stack.append((node.args[1], 0))
            stack.append(" -> ")
            stack.append((node.args[0], 1))
        elif kind == "tuple":
            if context >= 2:
                out.append("(")
                stack.append(")")
            stack.append((node.args[1], 2))
            stack.append(" * ")
            stack.append((node.args[0], 2))
        else:
            stack.append(" list")
            stack.append((node.args[0], 3))
    return "".join(out)


# ---------------------------------------------------------------- lexer

def _tokenize(src):
    tokens = []
    length = len(src)
    pos = 0
    while pos < length:
        ch = src[pos]
        if ch in _SPACES:
            pos += 1
        elif ch in _DIGITS:
            end = pos + 1
            while end < length and src[end] in _DIGITS:
                end += 1
            tokens.append(("int", src[pos:end]))
            pos = end
        elif ch in _NAME_START:
            end = pos + 1
            while end < length and src[end] in _NAME_REST:
                end += 1
            word = src[pos:end]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            pos = end
        elif src[pos:pos + 2] == "->" or src[pos:pos + 2] == "::":
            pair = src[pos:pos + 2]
            tokens.append((pair, pair))
            pos += 2
        elif ch in _SYMBOLS:
            tokens.append((ch, ch))
            pos += 1
        else:
            raise SyntaxError("unexpected character")
    tokens.append(("eof", ""))
    return tokens


# --------------------------------------------------------------- parser

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos][0]

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind):
        if self.tokens[self.pos][0] != kind:
            raise SyntaxError("expected " + kind)
        return self.advance()

    def parse(self):
        tree = self.parse_expr()
        if self.peek() != "eof":
            raise SyntaxError("unexpected token")
        return tree

    def parse_params(self):
        params = []
        while self.peek() == "name":
            params.append(self.advance()[1])
        return params

    def parse_expr(self):
        kind = self.peek()
        if kind == "fun":
            self.advance()
            params = self.parse_params()
            if not params:
                raise SyntaxError("fun needs a parameter")
            self.expect("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if kind == "let":
            self.advance()
            is_rec = False
            if self.peek() == "rec":
                self.advance()
                is_rec = True
            name = self.expect("name")[1]
            params = self.parse_params()
            if is_rec and not params:
                raise SyntaxError("let rec needs a parameter")
            self.expect("=")
            rhs = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            return ("letrec" if is_rec else "let", name, params, rhs, body)
        if kind == "if":
            self.advance()
            cond = self.parse_cmp()
            self.expect("then")
            then_branch = self.parse_expr()
            self.expect("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        node = self.parse_cons()
        while self.peek() == "=" or self.peek() == "<":
            op = self.advance()[0]
            node = ("bin", op, node, self.parse_cons())
        return node

    def parse_cons(self):
        operands = [self.parse_add()]
        while self.peek() == "::":
            self.advance()
            operands.append(self.parse_add())
        node = operands.pop()
        while operands:
            node = ("bin", "::", operands.pop(), node)
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.peek() == "+" or self.peek() == "-":
            op = self.advance()[0]
            node = ("bin", op, node, self.parse_mul())
        return node

    def parse_mul(self):
        node = self.parse_app()
        while self.peek() == "*":
            self.advance()
            node = ("bin", "*", node, self.parse_app())
        return node

    def parse_app(self):
        node = self.parse_atom()
        while self.peek() in _ATOM_START:
            node = ("app", node, self.parse_atom())
        return node

    def parse_atom(self):
        kind = self.peek()
        if kind == "int":
            self.advance()
            return ("int",)
        if kind == "name":
            return ("var", self.advance()[1])
        if kind == "true" or kind == "false":
            self.advance()
            return ("bool",)
        if kind == "[":
            self.advance()
            self.expect("]")
            return ("nil",)
        if kind == "(":
            self.advance()
            first = self.parse_expr()
            if self.peek() == ",":
                self.advance()
                second = self.parse_expr()
                self.expect(")")
                return ("tuple", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


# ------------------------------------------------------------ inference

def _builtins():
    def pair_first():
        alpha = _Var(_GENERIC)
        beta = _Var(_GENERIC)
        return _fn(_tup(alpha, beta), alpha)

    def pair_second():
        alpha = _Var(_GENERIC)
        beta = _Var(_GENERIC)
        return _fn(_tup(alpha, beta), beta)

    def list_head():
        alpha = _Var(_GENERIC)
        return _fn(_lst(alpha), alpha)

    def list_tail():
        alpha = _Var(_GENERIC)
        return _fn(_lst(alpha), _lst(alpha))

    def list_null():
        alpha = _Var(_GENERIC)
        return _fn(_lst(alpha), _BOOL)

    return {
        "fst": pair_first(),
        "snd": pair_second(),
        "hd": list_head(),
        "tl": list_tail(),
        "null": list_null(),
    }


class _Infer:
    def __init__(self):
        self.level = 0
        self.env = _builtins()

    def restore(self, name, old):
        if old is _MISSING:
            del self.env[name]
        else:
            self.env[name] = old

    def visit(self, node):
        tag = node[0]
        if tag == "var":
            scheme = self.env.get(node[1])
            if scheme is None:
                raise NameError(node[1])
            return _instantiate(scheme, self.level)
        if tag == "int":
            return _INT
        if tag == "bool":
            return _BOOL
        if tag == "app":
            fn_type = self.visit(node[1])
            arg_type = self.visit(node[2])
            result = _Var(self.level)
            _unify(fn_type, _fn(arg_type, result))
            return result
        if tag == "bin":
            op = node[1]
            if op == "+" or op == "-" or op == "*":
                _unify(self.visit(node[2]), _INT)
                _unify(self.visit(node[3]), _INT)
                return _INT
            if op == "<":
                _unify(self.visit(node[2]), _INT)
                _unify(self.visit(node[3]), _INT)
                return _BOOL
            if op == "=":
                left = self.visit(node[2])
                right = self.visit(node[3])
                _unify(left, right)
                return _BOOL
            head = self.visit(node[2])
            tail = self.visit(node[3])
            _unify(tail, _lst(head))
            return _lst(head)
        if tag == "if":
            _unify(self.visit(node[1]), _BOOL)
            then_type = self.visit(node[2])
            else_type = self.visit(node[3])
            _unify(then_type, else_type)
            return then_type
        if tag == "fun":
            params = node[1]
            saved = []
            param_types = []
            for name in params:
                param_type = _Var(self.level)
                saved.append((name, self.env.get(name, _MISSING)))
                self.env[name] = param_type
                param_types.append(param_type)
            result = self.visit(node[2])
            for index in range(len(saved) - 1, -1, -1):
                self.restore(saved[index][0], saved[index][1])
            for index in range(len(param_types) - 1, -1, -1):
                result = _fn(param_types[index], result)
            return result
        if tag == "let":
            name = node[1]
            params = node[2]
            rhs = ("fun", params, node[3]) if params else node[3]
            self.level += 1
            rhs_type = self.visit(rhs)
            self.level -= 1
            _generalize(rhs_type, self.level)
            old = self.env.get(name, _MISSING)
            self.env[name] = rhs_type
            result = self.visit(node[4])
            self.restore(name, old)
            return result
        if tag == "letrec":
            name = node[1]
            self.level += 1
            self_type = _Var(self.level)
            old = self.env.get(name, _MISSING)
            self.env[name] = self_type
            rhs_type = self.visit(("fun", node[2], node[3]))
            _unify(self_type, rhs_type)
            self.level -= 1
            _generalize(self_type, self.level)
            result = self.visit(node[4])
            self.restore(name, old)
            return result
        if tag == "tuple":
            first = self.visit(node[1])
            second = self.visit(node[2])
            return _tup(first, second)
        if tag == "nil":
            return _lst(_Var(self.level))
        raise SyntaxError("unknown node")


def infer(src: str) -> str:
    previous = sys.getrecursionlimit()
    if previous < _RECURSION_LIMIT:
        sys.setrecursionlimit(_RECURSION_LIMIT)
    try:
        tokens = _tokenize(src)
        tree = _Parser(tokens).parse()
        result = _Infer().visit(tree)
        return _show(result)
    finally:
        sys.setrecursionlimit(previous)
```
