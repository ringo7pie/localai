"""C1 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。"""


def split_words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    in_word = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\n":
            if in_word:
                words.append("".join(current))
                current = []
                in_word = False
            index += 1
        elif char == "#" and not in_word:
            newline = text.find("\n", index)
            index = length if newline < 0 else newline
        elif char == "'":
            close = text.find("'", index + 1)
            if close < 0:
                raise ValueError("unterminated single quote")
            current.append(text[index + 1:close])
            in_word = True
            index = close + 1
        elif char == '"':
            in_word = True
            index += 1
            while True:
                if index >= length:
                    raise ValueError("unterminated double quote")
                inner = text[index]
                if inner == '"':
                    index += 1
                    break
                if inner == "\\":
                    if index + 1 >= length:
                        raise ValueError("unterminated double quote")
                    following = text[index + 1]
                    if following == "\n":
                        index += 2
                    elif following in '"\\$`':
                        current.append(following)
                        index += 2
                    else:
                        current.append("\\")
                        index += 1
                else:
                    current.append(inner)
                    index += 1
        elif char == "\\":
            if index + 1 >= length:
                raise ValueError("trailing backslash")
            following = text[index + 1]
            if following != "\n":
                current.append(following)
                in_word = True
            index += 2
        else:
            current.append(char)
            in_word = True
            index += 1
    if in_word:
        words.append("".join(current))
    return words
