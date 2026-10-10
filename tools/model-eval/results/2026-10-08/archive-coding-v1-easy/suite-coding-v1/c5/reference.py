"""C5 の参照解（tests/test_units.py で隠しテストを確かめる用）。再帰下降の構文解析。"""

import re

_TOKEN = re.compile(r"\s*(?:([0-9]+(?:\.[0-9]+)?)|(.))")


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    stripped_end = len(expression.rstrip())
    while position < stripped_end:
        match = _TOKEN.match(expression, position)
        if match is None:
            raise ValueError("bad token")
        number, symbol = match.groups()
        if number is not None:
            # 数のすぐ後ろが数字か小数点なら、数の形が誤り（"3."、"1.2.3"）
            following = expression[match.end():match.end() + 1]
            if following == "." or following.isdigit():
                raise ValueError("bad number")
            tokens.append(number)
        elif symbol in "+-*/()":
            tokens.append(symbol)
        else:
            raise ValueError(f"unknown character: {symbol!r}")
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise ValueError("unexpected end")
        self.index += 1
        return token

    def expression(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.term()
            value = value + right if operator == "+" else value - right
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ("*", "/"):
            operator = self.take()
            right = self.unary()
            if operator == "*":
                value = value * right
            else:
                if right == 0:
                    raise ZeroDivisionError("division by zero")
                value = value / right
        return value

    def unary(self):
        negations = 0
        while self.peek() == "-":
            self.take()
            negations += 1
        value = self.primary()
        return -value if negations % 2 else value

    def primary(self):
        token = self.take()
        if token == "(":
            value = self.expression()
            if self.take() != ")":
                raise ValueError("missing )")
            return value
        if token[0].isdigit():
            return float(token) if "." in token else int(token)
        raise ValueError(f"unexpected token: {token!r}")


def evaluate(expression: str):
    tokens = _tokenize(expression)
    if not tokens:
        raise ValueError("empty expression")
    parser = _Parser(tokens)
    value = parser.expression()
    if parser.peek() is not None:
        raise ValueError(f"unexpected token: {parser.peek()!r}")
    return value
