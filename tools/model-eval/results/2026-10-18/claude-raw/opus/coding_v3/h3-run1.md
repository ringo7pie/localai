```python
import sys

_KEYWORDS = frozenset(
    ("fun", "let", "rec", "in", "if", "then", "else", "true", "false")
)
_LOWER_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = frozenset("0123456789")
_NAME_START = frozenset(_LOWER_LETTERS + "_")
_NAME_CHARS = frozenset(_LOWER_LETTERS + _LOWER_LETTERS.upper() + "0123456789_'")
_SPACES = frozenset(" \t\n")
_SINGLE_SYMBOLS = frozenset("()+*=<,")
_ATOM_START = frozenset(("int", "name", "true", "false", "[]", "("))

_GENERIC = 1 << 62
_RECURSION_LIMIT = 200000

_INT_NODE = ("int",)
_BOOL_NODE = ("bool",)
_NIL_NODE = ("nil",)


# ---------------------------------------------------------------- types


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


_T_INT = _TCon("int", ())
_T_BOOL = _TCon("bool", ())


def _prune(node):
    if node.__class__ is not _TVar or node.ref is None:
        return node
    root = node.ref
    while root.__class__ is _TVar and root.ref is not None:
        root = root.ref
    while node is not root:
        following = node.ref
        node.ref = root
        node = following
    return root


def _bind(var, target):
    if target.__class__ is _TVar:
        if target.level > var.level:
            target.level = var.level
        var.ref = target
        return
    if target.args:
        level = var.level
        stack = list(target.args)
        seen = {id(target)}
        while stack:
            node = _prune(stack.pop())
            if node.__class__ is _TVar:
                if node is var:
                    raise TypeError("recursive type")
                if node.level > level:
                    node.level = level
            elif node.args:
                key = id(node)
                if key not in seen:
                    seen.add(key)
                    stack.extend(node.args)
    var.ref = target


def _unify(left, right):
    stack = [(left, right)]
    seen = None
    while stack:
        first, second = stack.pop()
        first = _prune(first)
        second = _prune(second)
        if first is second:
            continue
        if first.__class__ is _TVar:
            _bind(first, second)
        elif second.__class__ is _TVar:
            _bind(second, first)
        else:
            if first.name != second.name or len(first.args) != len(second.args):
                raise TypeError("type mismatch")
            if not first.args:
                continue
            if seen is None:
                seen = set()
            key = (id(first), id(second))
            if key in seen:
                continue
            seen.add(key)
            stack.extend(zip(first.args, second.args))


def _generalize(node, level):
    stack = [node]
    seen = set()
    found = False
    while stack:
        current = _prune(stack.pop())
        if current.__class__ is _TVar:
            if current.level > level:
                current.level = _GENERIC
                found = True
        elif current.args:
            key = id(current)
            if key in seen:
                continue
            seen.add(key)
            stack.extend(current.args)
    return found


def _instantiate(node, level):
    memo = {}
    root = _prune(node)
    stack = [root]
    while stack:
        current = stack[-1]
        key = id(current)
        if key in memo:
            stack.pop()
            continue
        if current.__class__ is _TVar:
            memo[key] = _TVar(level) if current.level == _GENERIC else current
            stack.pop()
            continue
        args = current.args
        if not args:
            memo[key] = current
            stack.pop()
            continue
        pruned = [_prune(arg) for arg in args]
        missing = False
        for arg in pruned:
            if id(arg) not in memo:
                stack.append(arg)
                missing = True
        if missing:
            continue
        stack.pop()
        new_args = tuple(memo[id(arg)] for arg in pruned)
        changed = False
        for old, new in zip(pruned, new_args):
            if old is not new:
                changed = True
                break
        memo[key] = _TCon(current.name, new_args) if changed else current
    return memo[id(root)]


def _push_wrapped(stack, node):
    if node.__class__ is _TCon and (node.name == "->" or node.name == "*"):
        stack.append(")")
        stack.append(node)
        stack.append("(")
    else:
        stack.append(node)


def _show(node):
    names = {}
    pieces = []
    stack = [node]
    while stack:
        item = stack.pop()
        if item.__class__ is str:
            pieces.append(item)
            continue
        current = _prune(item)
        if current.__class__ is _TVar:
            key = id(current)
            label = names.get(key)
            if label is None:
                count = len(names)
                label = "'" + chr(97 + count % 26) + (str(count // 26) if count >= 26 else "")
                names[key] = label
            pieces.append(label)
            continue
        name = current.name
        if name == "->":
            left = _prune(current.args[0])
            stack.append(current.args[1])
            stack.append(" -> ")
            if left.__class__ is _TCon and left.name == "->":
                stack.append(")")
                stack.append(left)
                stack.append("(")
            else:
                stack.append(left)
        elif name == "*":
            left = _prune(current.args[0])
            right = _prune(current.args[1])
            _push_wrapped(stack, right)
            stack.append(" * ")
            _push_wrapped(stack, left)
        elif name == "list":
            stack.append(" list")
            _push_wrapped(stack, _prune(current.args[0]))
        else:
            pieces.append(name)
    return "".join(pieces)


# ---------------------------------------------------------------- lexer


def _tokenize(src):
    tokens = []
    length = len(src)
    index = 0
    while index < length:
        char = src[index]
        if char in _SPACES:
            index += 1
        elif char in _DIGITS:
            end = index + 1
            while end < length and src[end] in _DIGITS:
                end += 1
            tokens.append(("int", src[index:end]))
            index = end
        elif char in _NAME_START:
            end = index + 1
            while end < length and src[end] in _NAME_CHARS:
                end += 1
            word = src[index:end]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            index = end
        elif char == "-":
            if index + 1 < length and src[index + 1] == ">":
                tokens.append(("->", "->"))
                index += 2
            else:
                tokens.append(("-", "-"))
                index += 1
        elif char == ":":
            if index + 1 < length and src[index + 1] == ":":
                tokens.append(("::", "::"))
                index += 2
            else:
                raise SyntaxError("unexpected ':'")
        elif char == "[":
            if index + 1 < length and src[index + 1] == "]":
                tokens.append(("[]", "[]"))
                index += 2
            else:
                raise SyntaxError("'[' must be followed by ']'")
        elif char in _SINGLE_SYMBOLS:
            tokens.append((char, char))
            index += 1
        else:
            raise SyntaxError(f"unexpected character {char!r}")
    tokens.append(("eof", None))
    return tokens


# ---------------------------------------------------------------- parser


class _Parser:
    __slots__ = ("tokens", "pos")

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _expect(self, kind):
        if self.tokens[self.pos][0] != kind:
            raise SyntaxError(f"expected {kind!r}")
        self.pos += 1

    def _name(self):
        token = self.tokens[self.pos]
        if token[0] != "name":
            raise SyntaxError("expected a name")
        self.pos += 1
        return token[1]

    def parse(self):
        tree = self._expr()
        if self.tokens[self.pos][0] != "eof":
            raise SyntaxError("unexpected token")
        return tree

    def _expr(self):
        tokens = self.tokens
        kind = tokens[self.pos][0]
        if kind == "fun":
            self.pos += 1
            params = [self._name()]
            while tokens[self.pos][0] == "name":
                params.append(tokens[self.pos][1])
                self.pos += 1
            self._expect("->")
            body = self._expr()
            return ("fun", params, body)
        if kind == "let":
            self.pos += 1
            recursive = False
            if tokens[self.pos][0] == "rec":
                self.pos += 1
                recursive = True
            name = self._name()
            params = []
            while tokens[self.pos][0] == "name":
                params.append(tokens[self.pos][1])
                self.pos += 1
            if recursive and not params:
                raise SyntaxError("let rec needs at least one parameter")
            self._expect("=")
            bound = self._expr()
            self._expect("in")
            body = self._expr()
            if recursive:
                return ("letrec", name, params, bound, body)
            if params:
                bound = ("fun", params, bound)
            return ("let", name, bound, body)
        if kind == "if":
            self.pos += 1
            condition = self._expr()
            self._expect("then")
            then_branch = self._expr()
            self._expect("else")
            else_branch = self._expr()
            return ("if", condition, then_branch, else_branch)
        return self._cmp()

    def _cmp(self):
        tokens = self.tokens
        first = self._cons()
        rest = None
        while True:
            kind = tokens[self.pos][0]
            if kind != "=" and kind != "<":
                break
            self.pos += 1
            operand = self._cons()
            if rest is None:
                rest = []
            rest.append((kind, operand))
        return first if rest is None else ("ops", first, rest)

    def _cons(self):
        tokens = self.tokens
        first = self._add()
        if tokens[self.pos][0] != "::":
            return first
        items = [first]
        while tokens[self.pos][0] == "::":
            self.pos += 1
            items.append(self._add())
        return ("cons", items)

    def _add(self):
        tokens = self.tokens
        first = self._mul()
        rest = None
        while True:
            kind = tokens[self.pos][0]
            if kind != "+" and kind != "-":
                break
            self.pos += 1
            operand = self._mul()
            if rest is None:
                rest = []
            rest.append((kind, operand))
        return first if rest is None else ("ops", first, rest)

    def _mul(self):
        tokens = self.tokens
        first = self._app()
        rest = None
        while tokens[self.pos][0] == "*":
            self.pos += 1
            operand = self._app()
            if rest is None:
                rest = []
            rest.append(("*", operand))
        return first if rest is None else ("ops", first, rest)

    def _app(self):
        tokens = self.tokens
        head = self._atom()
        if tokens[self.pos][0] not in _ATOM_START:
            return head
        args = []
        while tokens[self.pos][0] in _ATOM_START:
            args.append(self._atom())
        return ("app", head, args)

    def _atom(self):
        token = self.tokens[self.pos]
        kind = token[0]
        if kind == "int":
            self.pos += 1
            return _INT_NODE
        if kind == "true" or kind == "false":
            self.pos += 1
            return _BOOL_NODE
        if kind == "name":
            self.pos += 1
            return ("var", token[1])
        if kind == "[]":
            self.pos += 1
            return _NIL_NODE
        if kind == "(":
            self.pos += 1
            inner = self._expr()
            if self.tokens[self.pos][0] == ",":
                self.pos += 1
                second = self._expr()
                self._expect(")")
                return ("tuple", inner, second)
            self._expect(")")
            return inner
        raise SyntaxError("unexpected token")


# ---------------------------------------------------------------- checker


class _Checker:
    def __init__(self):
        env = {}
        first = _TVar(_GENERIC)
        second = _TVar(_GENERIC)
        env["fst"] = (_TCon("->", (_TCon("*", (first, second)), first)), True)
        first = _TVar(_GENERIC)
        second = _TVar(_GENERIC)
        env["snd"] = (_TCon("->", (_TCon("*", (first, second)), second)), True)
        elem = _TVar(_GENERIC)
        env["hd"] = (_TCon("->", (_TCon("list", (elem,)), elem)), True)
        elem = _TVar(_GENERIC)
        env["tl"] = (
            _TCon("->", (_TCon("list", (elem,)), _TCon("list", (elem,)))),
            True,
        )
        elem = _TVar(_GENERIC)
        env["null"] = (_TCon("->", (_TCon("list", (elem,)), _T_BOOL)), True)
        self.env = env

    def _restore(self, name, previous):
        if previous is None:
            del self.env[name]
        else:
            self.env[name] = previous

    def _infer_fun(self, params, body, level):
        env = self.env
        saved = []
        param_types = []
        for name in params:
            var = _TVar(level)
            saved.append((name, env.get(name)))
            env[name] = (var, False)
            param_types.append(var)
        result = self.infer(body, level)
        for name, previous in reversed(saved):
            self._restore(name, previous)
        for var in reversed(param_types):
            result = _TCon("->", (var, result))
        return result

    def infer(self, node, level):
        kind = node[0]
        env = self.env
        if kind == "var":
            entry = env.get(node[1])
            if entry is None:
                raise NameError(f"name {node[1]!r} is not defined")
            if entry[1]:
                return _instantiate(entry[0], level)
            return entry[0]
        if kind == "int":
            return _T_INT
        if kind == "bool":
            return _T_BOOL
        if kind == "nil":
            return _TCon("list", (_TVar(level),))
        if kind == "app":
            func_type = self.infer(node[1], level)
            for argument in node[2]:
                arg_type = self.infer(argument, level)
                result = _TVar(level)
                _unify(func_type, _TCon("->", (arg_type, result)))
                func_type = result
            return func_type
        if kind == "ops":
            current = self.infer(node[1], level)
            for op, operand in node[2]:
                if op == "=":
                    right = self.infer(operand, level)
                    _unify(current, right)
                    current = _T_BOOL
                else:
                    _unify(current, _T_INT)
                    right = self.infer(operand, level)
                    _unify(right, _T_INT)
                    current = _T_BOOL if op == "<" else _T_INT
            return current
        if kind == "cons":
            types = [self.infer(item, level) for item in node[1]]
            result = types[-1]
            for position in range(len(types) - 2, -1, -1):
                _unify(result, _TCon("list", (types[position],)))
            return result
        if kind == "tuple":
            first = self.infer(node[1], level)
            second = self.infer(node[2], level)
            return _TCon("*", (first, second))
        if kind == "if":
            condition = self.infer(node[1], level)
            _unify(condition, _T_BOOL)
            then_type = self.infer(node[2], level)
            else_type = self.infer(node[3], level)
            _unify(then_type, else_type)
            return then_type
        if kind == "fun":
            return self._infer_fun(node[1], node[2], level)
        if kind == "let":
            name = node[1]
            bound = self.infer(node[2], level + 1)
            poly = _generalize(bound, level)
            previous = env.get(name)
            env[name] = (bound, poly)
            body = self.infer(node[3], level)
            self._restore(name, previous)
            return body
        if kind == "letrec":
            name = node[1]
            self_type = _TVar(level + 1)
            previous = env.get(name)
            env[name] = (self_type, False)
            func_type = self._infer_fun(node[2], node[3], level + 1)
            _unify(self_type, func_type)
            poly = _generalize(self_type, level)
            env[name] = (self_type, poly)
            body = self.infer(node[4], level)
            self._restore(name, previous)
            return body
        raise SyntaxError("unknown node")


# ---------------------------------------------------------------- entry


def infer(src: str) -> str:
    previous_limit = sys.getrecursionlimit()
    if previous_limit < _RECURSION_LIMIT:
        sys.setrecursionlimit(_RECURSION_LIMIT)
    try:
        tokens = _tokenize(src)
        tree = _Parser(tokens).parse()
        result = _Checker().infer(tree, 0)
        return _show(result)
    finally:
        if sys.getrecursionlimit() != previous_limit:
            sys.setrecursionlimit(previous_limit)
```
