"""C4 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。

再帰を使わず、入れ子の容器を自前のスタックに積んで読む（深さ 50,000 でも落ちない）。
"""

import re

_WHITESPACE = re.compile(r"[ \t\n\r]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_PLAIN_CHARS = re.compile(r'[^"\\\x00-\x1f]*')
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _skip(text: str, index: int) -> int:
    return _WHITESPACE.match(text, index).end()


def _hex4(text: str, index: int) -> int:
    match = _HEX4.match(text, index)
    if match is None:
        raise ValueError(f"bad \\u escape at {index}")
    return int(match.group(), 16)


def _parse_string(text: str, index: int) -> tuple[str, int]:
    """text[index] == '"' から読み、(文字列, 閉じ引用符の次の位置) を返す。"""

    if index >= len(text) or text[index] != '"':
        raise ValueError(f"expected string at {index}")
    parts: list[str] = []
    position = index + 1
    length = len(text)
    while True:
        match = _PLAIN_CHARS.match(text, position)
        parts.append(match.group())
        position = match.end()
        if position >= length:
            raise ValueError("unterminated string")
        char = text[position]
        if char == '"':
            return "".join(parts), position + 1
        if char != "\\":
            raise ValueError(f"control character in string at {position}")
        if position + 1 >= length:
            raise ValueError("unterminated string")
        escape = text[position + 1]
        if escape in _SIMPLE_ESCAPES:
            parts.append(_SIMPLE_ESCAPES[escape])
            position += 2
        elif escape == "u":
            code = _hex4(text, position + 2)
            position += 6
            if 0xD800 <= code <= 0xDBFF:
                if not text.startswith("\\u", position):
                    raise ValueError("lone high surrogate")
                low = _hex4(text, position + 2)
                if not 0xDC00 <= low <= 0xDFFF:
                    raise ValueError("high surrogate not followed by low surrogate")
                code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                position += 6
            elif 0xDC00 <= code <= 0xDFFF:
                raise ValueError("lone low surrogate")
            parts.append(chr(code))
        else:
            raise ValueError(f"bad escape \\{escape}")


def _parse_key(text: str, index: int) -> tuple[str, int]:
    """オブジェクトのキーと ':' を読み、(キー, ':' の次の空白を飛ばした位置) を返す。"""

    key, index = _parse_string(text, _skip(text, index))
    index = _skip(text, index)
    if index >= len(text) or text[index] != ":":
        raise ValueError(f"expected ':' at {index}")
    return key, _skip(text, index + 1)


def parse_json(text: str) -> object:
    length = len(text)
    index = _skip(text, 0)
    # スタックの要素: [list] か [dict, 待っているキー]
    stack: list[list] = []
    while True:
        if index >= length:
            raise ValueError("unexpected end of input")
        char = text[index]
        if char == "{":
            index = _skip(text, index + 1)
            if index < length and text[index] == "}":
                value: object = {}
                index += 1
            else:
                key, index = _parse_key(text, index)
                stack.append([{}, key])
                continue
        elif char == "[":
            index = _skip(text, index + 1)
            if index < length and text[index] == "]":
                value = []
                index += 1
            else:
                stack.append([[]])
                continue
        elif char == '"':
            value, index = _parse_string(text, index)
        elif text.startswith("true", index):
            value, index = True, index + 4
        elif text.startswith("false", index):
            value, index = False, index + 5
        elif text.startswith("null", index):
            value, index = None, index + 4
        else:
            match = _NUMBER.match(text, index)
            if match is None:
                raise ValueError(f"unexpected character at {index}")
            token = match.group()
            value = float(token) if (match.group(1) or match.group(2)) else int(token)
            index = match.end()
        # 読めた値を容器に入れる。容器が閉じたら、その容器を値として 1 つ外側へ渡す
        while True:
            index = _skip(text, index)
            if not stack:
                if index != length:
                    raise ValueError(f"trailing characters at {index}")
                return value
            top = stack[-1]
            if len(top) == 1:
                top[0].append(value)
                if index < length and text[index] == ",":
                    index = _skip(text, index + 1)
                    break
                if index < length and text[index] == "]":
                    value = stack.pop()[0]
                    index += 1
                    continue
                raise ValueError(f"expected ',' or ']' at {index}")
            container, key = top
            if key in container:
                raise ValueError(f"duplicate key {key!r}")
            container[key] = value
            if index < length and text[index] == ",":
                top[1], index = _parse_key(text, index + 1)
                break
            if index < length and text[index] == "}":
                value = stack.pop()[0]
                index += 1
                continue
            raise ValueError(f"expected ',' or '}}' at {index}")
