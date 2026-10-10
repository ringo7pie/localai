## Problem C5: Matcher for a subset of regular expressions

Write a function `regex_search(pattern: str, text: str) -> bool`. It returns `True` if `pattern` matches some substring of `text` (including the empty substring), and `False` otherwise. Do not use the standard library's `re` module (nor `sre_parse`, `sre_compile`, or `_sre`); an answer that uses it scores 0.

### Pattern grammar

- Characters: An ordinary character matches that character itself. Upper case and lower case are distinguished.
- `.`: Matches any single character, including a newline.
- A single character immediately after `\`: Matches that character itself (`\.` is `.`, `\\` is `\`, `\n` is `n` and not a newline, and `\d` is `d`). A lone `\` at the end of the pattern is a `ValueError`.
- Character class `[...]`: A `^` immediately after `[` means negation (`[^...]` is any single character other than the listed ones). The contents are read from left to right as items. To read an item, first read one character (a character escaped with `\` also counts as one character, and becomes the unescaped character); if the character right after it is `-` and the character after that is not `]`, the item is a range `x-y` (the code points from `x` to `y` inclusive; `y` can also be escaped; it is a `ValueError` if `x > y`); otherwise the item is just the one character that was read. `]` always closes the class unless it is escaped. `-` is an ordinary character when it is read as the first character of an item, or when it comes immediately before `]`. Inside a class, `.` `*` `+` `?` `|` `(` `)` `^` (other than at the start) and `$` are ordinary characters. `[]` and `[^]` with no items at all, and an unclosed `[`, are a `ValueError`.
- `^`: A zero-width assertion that matches only at the start of `text` (position 0). `$`: A zero-width assertion that matches only at the end of `text` (it does not match before a trailing newline). They may be placed anywhere in the pattern.
- Quantifiers `*` (zero or more times), `+` (one or more times), and `?` (zero or one time): These apply to the immediately preceding element (a single character, `.`, an escaped character, a character class, or a group `(...)`). It is a `ValueError` when there is no element to apply to (at the start of the pattern, or right after `(` or `|`), when quantifiers are stacked (`a**`, `a*?`), or when one is applied to `^` or `$`.
- Group `( ... )`: Groups its contents into a single element (capturing is not needed). The empty group `()` matches the empty string. An unmatched `(` or `)` is a `ValueError`.
- Alternation `|`: It has the lowest precedence, and matching either the left side or the right side is enough. An empty alternative (`a|`, `|a`, `(|a)`) matches the empty string.
- The empty pattern `""` matches any `text` (`True`).

### Performance

- `pattern` is at most 100 characters, and `text` is at most 10,000 characters.
- Implementations whose backtracking takes exponential time are not acceptable. Even when matching `(a|aa)*b` or `(a*)*b` against `"aaaa…a"` (which does not match), or matching `a*b` against a 5,000-character `"aaaa…a"`, the answer must come back quickly (use an approach such as walking a set of states).

Examples:
- `regex_search("^[a-z]+@[a-z]+\\.[a-z]+$", "foo@bar.com")` → `True`
- `regex_search("(cat|dog)s?$", "I like dogs")` → `True`
- `regex_search("a$", "a\n")` → `False`
