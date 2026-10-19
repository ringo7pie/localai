```python
import sys

_GENERIC_LEVEL = 1 << 30
_RECURSION_LIMIT = 300000

_KEYWORDS = frozenset(["fun", "let", "rec", "in", "if", "then", "else", "true", "false"])
_DIGITS = frozenset("0123456789")
_NAME_START = frozenset("abcdefghijklmnopqrstuvwxyz_")
_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'")
_SINGLE_SYMBOLS = frozenset("(),+-*=<[]")
_ATOM_START = frozenset(["int", "name", "true", "false", "(", "["])

_INT_NODE = ("int",)
_BOOL_NODE = ("bool",)
_NIL_NODE = ("nil",)


# ---------------------------------------------------------------- lexer

def _tokenize(src):
    tokens = []
    length = len(src)
    pos = 0
    while pos < length:
        char = src[pos]
        if char == " " or char == "\t" or char == "\n":
            pos += 1
        elif char in _DIGITS:
            start = pos
            pos += 1
            while pos < length and src[pos] in _DIGITS:
                pos += 1
            tokens.append(("int", src[start:pos]))
        elif char in _NAME_START:
            start = pos
            pos += 1
            while pos < length and src[pos] in _NAME_CHARS:
                pos += 1
            word = src[start:pos]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
        elif char == "-" and pos + 1 < length and src[pos + 1] == ">":
            tokens.append(("->", "->"))
            pos += 2
        elif char == ":" and pos + 1 < length and src[pos + 1] == ":":
            tokens.append(("::", "::"))
            pos += 2
        elif char in _SINGLE_SYMBOLS:
            tokens.append((char, char))
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

    def expect(self, kind):
        if self.tokens[self.pos][0] != kind:
            raise SyntaxError("expected " + kind)
        self.pos += 1

    def expect_name(self):
        kind, text = self.tokens[self.pos]
        if kind != "name":
            raise SyntaxError("expected a name")
        self.pos += 1
        return text

    def parse_names(self):
        names = []
        while self.tokens[self.pos][0] == "name":
            names.append(self.tokens[self.pos][1])
            self.pos += 1
        return names

    def parse_program(self):
        tree = self.parse_expr()
        if self.tokens[self.pos][0] != "eof":
            raise SyntaxError("unexpected token")
        return tree

    def parse_expr(self):
        kind = self.tokens[self.pos][0]
        if kind == "fun":
            self.pos += 1
            params = self.parse_names()
            if not params:
                raise SyntaxError("fun needs a parameter")
            self.expect("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if kind == "let":
            self.pos += 1
            is_rec = False
            if self.tokens[self.pos][0] == "rec":
                self.pos += 1
                is_rec = True
            name = self.expect_name()
            params = self.parse_names()
            if is_rec and not params:
                raise SyntaxError("let rec needs a parameter")
            self.expect("=")
            bound = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            if params:
                bound = ("fun", params, bound)
            if is_rec:
                return ("letrec", name, bound, body)
            return ("let", name, bound, body)
        if kind == "if":
            self.pos += 1
            cond = self.parse_expr()
            self.expect("then")
            then_branch = self.parse_expr()
            self.expect("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.tokens[self.pos][0] == "=" or self.tokens[self.pos][0] == "<":
            op = self.tokens[self.pos][0]
            self.pos += 1
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        operands = [self.parse_add()]
        while self.tokens[self.pos][0] == "::":
            self.pos += 1
            operands.append(self.parse_add())
        result = operands.pop()
        while operands:
            result = ("bin", "::", operands.pop(), result)
        return result

    def parse_add(self):
        left = self.parse_mul()
        while self.tokens[self.pos][0] == "+" or self.tokens[self.pos][0] == "-":
            op = self.tokens[self.pos][0]
            self.pos += 1
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.tokens[self.pos][0] == "*":
            self.pos += 1
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def parse_app(self):
        node = self.parse_atom()
        while self.tokens[self.pos][0] in _ATOM_START:
            argument = self.parse_atom()
            node = ("app", node, argument)
        return node

    def parse_atom(self):
        kind, text = self.tokens[self.pos]
        if kind == "int":
            self.pos += 1
            return _INT_NODE
        if kind == "true" or kind == "false":
            self.pos += 1
            return _BOOL_NODE
        if kind == "name":
            self.pos += 1
            return ("var", text)
        if kind == "[":
            self.pos += 1
            self.expect("]")
            return _NIL_NODE
        if kind == "(":
            self.pos += 1
            first = self.parse_expr()
            if self.tokens[self.pos][0] == ",":
                self.pos += 1
                second = self.parse_expr()
                self.expect(")")
                return ("pair", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


# ---------------------------------------------------------------- types

class _Var:
    __slots__ = ("link", "level")

    def __init__(self, level):
        self.link = None
        self.level = level


class _Con:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _Con("int", ())
_BOOL = _Con("bool", ())


def _fn(argument, result):
    return _Con("->", (argument, result))


def _pair(first, second):
    return _Con("*", (first, second))


def _list(element):
    return _Con("list", (element,))


def _prune(ty):
    root = ty
    while root.__class__ is _Var and root.link is not None:
        root = root.link
    while ty.__class__ is _Var and ty.link is not None:
        following = ty.link
        ty.link = root
        ty = following
    return root


def _bind(var, ty):
    level = var.level
    seen = set()
    stack = [ty]
    while stack:
        node = _prune(stack.pop())
        if node is var:
            raise TypeError("infinite type")
        key = id(node)
        if key in seen:
            continue
        seen.add(key)
        if node.__class__ is _Var:
            if node.level > level:
                node.level = level
        else:
            stack.extend(node.args)
    var.link = ty


def _unify(left, right):
    stack = [(left, right)]
    while stack:
        first, second = stack.pop()
        first = _prune(first)
        second = _prune(second)
        if first is second:
            continue
        if first.__class__ is _Var:
            _bind(first, second)
        elif second.__class__ is _Var:
            _bind(second, first)
        else:
            if first.name != second.name or len(first.args) != len(second.args):
                raise TypeError("type mismatch")
            stack.extend(zip(first.args, second.args))


def _generalize(ty, level):
    found = False
    seen = set()
    stack = [ty]
    while stack:
        node = _prune(stack.pop())
        key = id(node)
        if key in seen:
            continue
        seen.add(key)
        if node.__class__ is _Var:
            if node.level > level:
                node.level = _GENERIC_LEVEL
                found = True
        else:
            stack.extend(node.args)
    return found


def _instantiate(ty, level):
    root = _prune(ty)
    done = {}
    stack = [root]
    while stack:
        node = stack[-1]
        key = id(node)
        if key in done:
            stack.pop()
            continue
        if node.__class__ is _Var:
            if node.level == _GENERIC_LEVEL:
                done[key] = _Var(level)
            else:
                done[key] = node
            stack.pop()
            continue
        if not node.args:
            done[key] = node
            stack.pop()
            continue
        children = [_prune(argument) for argument in node.args]
        missing = [child for child in children if id(child) not in done]
        if missing:
            stack.extend(missing)
            continue
        stack.pop()
        copies = [done[id(child)] for child in children]
        changed = False
        for index in range(len(children)):
            if children[index] is not copies[index]:
                changed = True
        if changed:
            done[key] = _Con(node.name, tuple(copies))
        else:
            done[key] = node
    return done[id(root)]


def _var_name(index):
    suffix = str(index // 26) if index >= 26 else ""
    return "'" + chr(97 + index % 26) + suffix


def _show(ty):
    names = {}
    output = []
    stack = [(ty, 0)]
    while stack:
        item = stack.pop()
        if item.__class__ is str:
            output.append(item)
            continue
        node, need = item
        node = _prune(node)
        if node.__class__ is _Var:
            key = id(node)
            name = names.get(key)
            if name is None:
                name = _var_name(len(names))
                names[key] = name
            output.append(name)
            continue
        kind = node.name
        if kind == "int" or kind == "bool":
            output.append(kind)
            continue
        if kind == "list":
            precedence = 2
            parts = [(node.args[0], 2), " list"]
        elif kind == "*":
            precedence = 1
            parts = [(node.args[0], 2), " * ", (node.args[1], 2)]
        else:
            precedence = 0
            parts = [(node.args[0], 1), " -> ", (node.args[1], 0)]
        if precedence < need:
            parts = ["("] + parts + [")"]
        for part in reversed(parts):
            stack.append(part)
    return "".join(output)


# ------------------------------------------------------------ inference

def _initial_env():
    env = {}
    alpha = _Var(_GENERIC_LEVEL)
    beta = _Var(_GENERIC_LEVEL)
    env["fst"] = (_fn(_pair(alpha, beta), alpha), True)
    alpha = _Var(_GENERIC_LEVEL)
    beta = _Var(_GENERIC_LEVEL)
    env["snd"] = (_fn(_pair(alpha, beta), beta), True)
    alpha = _Var(_GENERIC_LEVEL)
    env["hd"] = (_fn(_list(alpha), alpha), True)
    alpha = _Var(_GENERIC_LEVEL)
    env["tl"] = (_fn(_list(alpha), _list(alpha)), True)
    alpha = _Var(_GENERIC_LEVEL)
    env["null"] = (_fn(_list(alpha), _BOOL), True)
    return env


def _push(env, name, entry):
    previous = env.get(name)
    env[name] = entry
    return previous


def _pop(env, name, previous):
    if previous is None:
        del env[name]
    else:
        env[name] = previous


def _infer(node, env, level):
    tag = node[0]
    if tag == "var":
        entry = env.get(node[1])
        if entry is None:
            raise NameError(node[1])
        ty, poly = entry
        if poly:
            return _instantiate(ty, level)
        return ty
    if tag == "int":
        return _INT
    if tag == "bool":
        return _BOOL
    if tag == "app":
        func_type = _infer(node[1], env, level)
        arg_type = _infer(node[2], env, level)
        result = _Var(level)
        _unify(func_type, _fn(arg_type, result))
        return result
    if tag == "bin":
        op = node[1]
        if op == "=":
            left_type = _infer(node[2], env, level)
            right_type = _infer(node[3], env, level)
            _unify(left_type, right_type)
            return _BOOL
        if op == "::":
            head_type = _infer(node[2], env, level)
            tail_type = _infer(node[3], env, level)
            _unify(tail_type, _list(head_type))
            return tail_type
        left_type = _infer(node[2], env, level)
        _unify(left_type, _INT)
        right_type = _infer(node[3], env, level)
        _unify(right_type, _INT)
        if op == "<":
            return _BOOL
        return _INT
    if tag == "if":
        cond_type = _infer(node[1], env, level)
        _unify(cond_type, _BOOL)
        then_type = _infer(node[2], env, level)
        else_type = _infer(node[3], env, level)
        _unify(then_type, else_type)
        return then_type
    if tag == "fun":
        params = node[1]
        param_types = []
        previous_entries = []
        for name in params:
            param_var = _Var(level)
            param_types.append(param_var)
            previous_entries.append(_push(env, name, (param_var, False)))
        result = _infer(node[2], env, level)
        for index in range(len(params) - 1, -1, -1):
            _pop(env, params[index], previous_entries[index])
            result = _fn(param_types[index], result)
        return result
    if tag == "let":
        bound_type = _infer(node[2], env, level + 1)
        poly = _generalize(bound_type, level)
        previous = _push(env, node[1], (bound_type, poly))
        result = _infer(node[3], env, level)
        _pop(env, node[1], previous)
        return result
    if tag == "letrec":
        name = node[1]
        rec_var = _Var(level + 1)
        previous = _push(env, name, (rec_var, False))
        bound_type = _infer(node[2], env, level + 1)
        _unify(rec_var, bound_type)
        _pop(env, name, previous)
        poly = _generalize(rec_var, level)
        previous = _push(env, name, (rec_var, poly))
        result = _infer(node[3], env, level)
        _pop(env, name, previous)
        return result
    if tag == "pair":
        first_type = _infer(node[1], env, level)
        second_type = _infer(node[2], env, level)
        return _pair(first_type, second_type)
    if tag == "nil":
        return _list(_Var(level))
    raise SyntaxError("unknown node")


def infer(src: str) -> str:
    old_limit = sys.getrecursionlimit()
    if old_limit < _RECURSION_LIMIT:
        sys.setrecursionlimit(_RECURSION_LIMIT)
    try:
        tokens = _tokenize(src)
        tree = _Parser(tokens).parse_program()
        result_type = _infer(tree, _initial_env(), 0)
        return _show(result_type)
    finally:
        sys.setrecursionlimit(old_limit)
```
