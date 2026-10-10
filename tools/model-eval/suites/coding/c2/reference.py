"""C2 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。"""

from datetime import datetime, timedelta

MONTH_NAMES = {name: index + 1 for index, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
DAY_NAMES = {name: index for index, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}
# (最小, 最大, 名前の表)
FIELD_SPECS = [(0, 59, None), (0, 23, None), (1, 31, None), (1, 12, MONTH_NAMES), (0, 7, DAY_NAMES)]


def _parse_value(token: str, low: int, high: int, names: dict[str, int] | None) -> int:
    if names is not None and token.upper() in names:
        return names[token.upper()]
    if not token.isdigit() or not token.isascii():
        raise ValueError(f"bad value {token!r}")
    value = int(token)
    if value < low or value > high:
        raise ValueError(f"value {value} out of range {low}-{high}")
    return value


def _parse_step(token: str) -> int:
    if not token.isdigit() or not token.isascii():
        raise ValueError(f"bad step {token!r}")
    step = int(token)
    if step < 1:
        raise ValueError("step must be >= 1")
    return step


def _parse_field(field: str, low: int, high: int, names: dict[str, int] | None) -> set[int]:
    values: set[int] = set()
    for item in field.split(","):
        if item == "":
            raise ValueError("empty item")
        step = 1
        if "/" in item:
            base, _, step_text = item.partition("/")
            step = _parse_step(step_text)
            if base != "*" and "-" not in base:
                raise ValueError("step without range")
        else:
            base = item
        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, _, right = base.partition("-")
            start = _parse_value(left, low, high, names)
            end = _parse_value(right, low, high, names)
            if start > end:
                raise ValueError("reversed range")
        else:
            start = end = _parse_value(base, low, high, names)
        values.update(range(start, end + 1, step))
    return values


def next_run(expression: str, after: datetime) -> datetime | None:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("expected 5 fields")
    parsed = [_parse_field(field, *spec) for field, spec in zip(fields, FIELD_SPECS)]
    minutes, hours, days, months, weekdays = parsed
    if 7 in weekdays:
        weekdays.discard(7)
        weekdays.add(0)
    day_star = fields[2] == "*"
    weekday_star = fields[4] == "*"
    sorted_minutes = sorted(minutes)
    sorted_hours = sorted(hours)
    last_year = after.year + 10

    def day_matches(day: datetime) -> bool:
        if day.month not in months:
            return False
        by_day = day.day in days
        by_weekday = (day.weekday() + 1) % 7 in weekdays
        if day_star and weekday_star:
            return True
        if day_star:
            return by_weekday
        if weekday_star:
            return by_day
        return by_day or by_weekday

    start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    current_day = start.replace(hour=0, minute=0)
    first = True
    while current_day.year <= last_year:
        if day_matches(current_day):
            for hour in sorted_hours:
                if first and hour < start.hour:
                    continue
                for minute in sorted_minutes:
                    if first and hour == start.hour and minute < start.minute:
                        continue
                    return current_day.replace(hour=hour, minute=minute)
        first = False
        current_day += timedelta(days=1)
    return None
