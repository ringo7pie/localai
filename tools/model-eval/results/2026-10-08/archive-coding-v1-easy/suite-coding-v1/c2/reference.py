"""C2 の参照解（tests/test_units.py で隠しテストを確かめる用）。"""

import re

_PATTERN = re.compile(r" *(?:([0-9]+)d *)?(?:([0-9]+)h *)?(?:([0-9]+)m *)?(?:([0-9]+)s *)?")
_UNIT_SECONDS = (86400, 3600, 60, 1)


def parse_duration(text: str) -> int:
    match = _PATTERN.fullmatch(text)
    if match is None or all(group is None for group in match.groups()):
        raise ValueError(f"invalid duration: {text!r}")
    return sum(int(group) * unit for group, unit in zip(match.groups(), _UNIT_SECONDS) if group is not None)
