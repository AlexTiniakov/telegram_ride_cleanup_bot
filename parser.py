import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Kyiv")
DELETE_DELAY = timedelta(minutes=5)
# Rides for tomorrow may be announced only from this local hour of the current day.
NEXT_DAY_OPEN_HOUR = 15

POST_TAG_RE = re.compile(
    r"#\s*(?:водій|водитель|пасажир|пассажир)\b",
    re.IGNORECASE,
)

NUMERIC_DATE_RE = re.compile(
    r"(?<![\d:.])"
    r"(?P<day>0?[1-9]|[12]\d|3[01])[^\S\r\n]*"
    r"(?P<sep>[.,/-])[^\S\r\n]*"
    r"(?P<month>0?[1-9]|1[0-2])"
    r"(?:[^\S\r\n]*[.,/-][^\S\r\n]*(?P<year>\d{4}|\d{2})(?![\d:]|\.\d))?"
    r"[^\S\r\n]*(?:р\.?|року|г\.?|года)?"
    r"(?![\d:])",
    re.IGNORECASE,
)

MONTH_ALIASES = {
    # Ukrainian
    "січ": 1, "січня": 1, "січень": 1,
    "лют": 2, "лютого": 2, "лютий": 2,
    "бер": 3, "березня": 3, "березень": 3,
    "кві": 4, "квіт": 4, "квітня": 4, "квітень": 4,
    "тра": 5, "трав": 5, "травня": 5, "травень": 5,
    "чер": 6, "черв": 6, "червня": 6, "червень": 6,
    "лип": 7, "липня": 7, "липень": 7,
    "сер": 8, "серп": 8, "серпня": 8, "серпень": 8,
    "вер": 9, "верес": 9, "вересня": 9, "вересень": 9,
    "жов": 10, "жовт": 10, "жовтня": 10, "жовтень": 10,
    "лис": 11, "лист": 11, "листопада": 11, "листопад": 11,
    "гру": 12, "груд": 12, "грудня": 12, "грудень": 12,
    # Russian
    "янв": 1, "января": 1, "январь": 1,
    "фев": 2, "февраля": 2, "февраль": 2,
    "мар": 3, "марта": 3, "март": 3,
    "апр": 4, "апреля": 4, "апрель": 4,
    "май": 5, "мая": 5,
    "июн": 6, "июня": 6, "июнь": 6,
    "июл": 7, "июля": 7, "июль": 7,
    "авг": 8, "августа": 8, "август": 8,
    "сен": 9, "сент": 9, "сентября": 9, "сентябрь": 9,
    "окт": 10, "октября": 10, "октябрь": 10,
    "ноя": 11, "нояб": 11, "ноября": 11, "ноябрь": 11,
    "дек": 12, "декабря": 12, "декабрь": 12,
}

_MONTH_PATTERN = "|".join(
    sorted((re.escape(k) for k in MONTH_ALIASES), key=len, reverse=True)
)
TEXT_DATE_RE = re.compile(
    rf"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])[^\S\r\n]*"
    rf"(?P<month>{_MONTH_PATTERN})\.?,?"
    rf"(?:[^\S\r\n]+(?P<year>\d{{4}}|\d{{2}}(?![^\S\r\n]*[:.][^\S\r\n]*\d)))?"
    rf"[^\S\r\n]*(?:р\.?|року|г\.?|года)?\b",
    re.IGNORECASE,
)

TIME_RE = re.compile(
    r"(?<!\d)(?P<h>[01]?\d|2[0-3])\s*[:.]\s*(?P<m>[0-5]\d)(?!\d)"
)
DASH_TIME_RE = re.compile(
    r"(?<![\d:])(?P<h>[01]?\d|2[0-3])\s*-\s*(?P<m>[0-5]\d)(?!\d)"
)
FULL_RANGE_RE = re.compile(
    r"(?<!\d)"
    r"(?P<h1>[01]?\d|2[0-3])\s*[:.]\s*(?P<m1>[0-5]\d)"
    r"\s*(?:-|–|—|−|\.{2,}|…|до|to)\s*"
    r"(?P<h2>[01]?\d|2[0-3])\s*[:.]\s*(?P<m2>[0-5]\d)"
    r"(?!\d)",
    re.IGNORECASE,
)
SHORT_RANGE_RE = re.compile(
    r"(?<!\d)"
    r"(?P<h1>[01]?\d|2[0-3])\s*[:.]\s*(?P<m1>[0-5]\d)"
    r"\s*(?:-|–|—|−|\.{2,}|…|до)\s*"
    r"(?P<m2>[0-5]\d)"
    r"(?!\s*[:.]\s*\d)(?!\d)",
    re.IGNORECASE,
)
WORDS_TIME_RE = re.compile(
    r"(?<!\d)(?P<h>[01]?\d|2[0-3])\s*"
    r"(?:год(?:\.|ини|ина|ин)?|г|ч(?:\.|ас(?:а|ов)?)?)\s*"
    r"(?P<m>[0-5]?\d)\s*"
    r"(?:хв(?:\.|илин(?:а|и)?)?|мин(?:\.|ут(?:а|ы)?)?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedRideTime:
    trip_start: datetime
    trip_end: datetime
    delete_at: datetime
    date_text: str
    time_text: str


def normalize_text(text: str) -> str:
    return (
        text.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("−", "-")
    )


def parse_year(year_text: str | None, reference_date: date, day: int, month: int) -> int:
    if year_text:
        year = int(year_text)
        return 2000 + year if len(year_text) == 2 else year

    year = reference_date.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year

    # e.g. on 30 Dec, "02.01" means Jan of the next year.
    if candidate < reference_date - timedelta(days=180):
        year += 1
    return year


def extract_date(text: str, reference_date: date) -> tuple[date, str, tuple[int, int]] | None:
    for m in NUMERIC_DATE_RE.finditer(text):
        # A lone ambiguous 17.05 or 7-05 is a time. Treat it as a date
        # only when another time remains outside the complete date token.
        if m.group("year") is None and m.group("sep") in (".", "-"):
            if int(m.group("day")) <= 23:
                remaining = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
                # Do not split a time range into a date and another time.
                in_range = any(
                    r.start() <= m.start() < r.end()
                    for pattern in (FULL_RANGE_RE, SHORT_RANGE_RE)
                    for r in pattern.finditer(text)
                )
                if in_range or extract_time(remaining, reference_date) is None:
                    continue
        day = int(m.group("day"))
        month = int(m.group("month"))
        year = parse_year(m.group("year"), reference_date, day, month)
        try:
            return date(year, month, day), m.group(0).strip(), m.span()
        except ValueError:
            return None

    m = TEXT_DATE_RE.search(text)
    if m:
        day = int(m.group("day"))
        month_key = m.group("month").lower().rstrip(".")
        month = MONTH_ALIASES[month_key]
        year = parse_year(m.group("year"), reference_date, day, month)
        try:
            return date(year, month, day), m.group(0).strip(), m.span()
        except ValueError:
            return None

    return None


def _combine(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def extract_time(text: str, ride_date: date) -> tuple[datetime, datetime, str] | None:
    m = FULL_RANGE_RE.search(text)
    if m:
        start = _combine(ride_date, int(m.group("h1")), int(m.group("m1")))
        end = _combine(ride_date, int(m.group("h2")), int(m.group("m2")))
        if end < start:
            end += timedelta(days=1)
        return start, end, m.group(0).strip()

    m = SHORT_RANGE_RE.search(text)
    if m:
        h1 = int(m.group("h1"))
        m1 = int(m.group("m1"))
        m2 = int(m.group("m2"))
        start = _combine(ride_date, h1, m1)
        end = _combine(ride_date, h1, m2)
        if end < start:
            end += timedelta(hours=1)
        return start, end, m.group(0).strip()

    m = TIME_RE.search(text)
    if m:
        dt = _combine(ride_date, int(m.group("h")), int(m.group("m")))
        return dt, dt, m.group(0).strip()

    m = DASH_TIME_RE.search(text)
    if m:
        dt = _combine(ride_date, int(m.group("h")), int(m.group("m")))
        return dt, dt, m.group(0).strip()

    m = WORDS_TIME_RE.search(text)
    if m:
        dt = _combine(ride_date, int(m.group("h")), int(m.group("m")))
        return dt, dt, m.group(0).strip()

    return None


def has_ride_time(text: str, message_dt: datetime) -> bool:
    """Check time independently of date validity, masking explicit dates."""
    text = normalize_text(text)
    reference = message_dt.astimezone(TZ).date()
    result = extract_date(text, reference)
    spans = [result[2]] if result else []
    spans.extend(m.span() for m in TEXT_DATE_RE.finditer(text))
    spans.extend(
        m.span() for m in NUMERIC_DATE_RE.finditer(text)
        if m.group("year") is not None or m.group("sep") == "/"
        or int(m.group("day")) > 23
    )
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return extract_time("".join(chars), reference) is not None


def is_ride_date_allowed(ride_date: date, message_dt: datetime) -> bool:
    """Today's rides are always allowed; tomorrow's only from 15:00; later never.

    Past dates stay allowed: they are simply deleted by the next cleanup pass.
    """
    message_local = message_dt.astimezone(TZ)
    today = message_local.date()
    if ride_date <= today:
        return True
    if ride_date == today + timedelta(days=1):
        return message_local.hour >= NEXT_DAY_OPEN_HOUR
    return False


def parse_ride_datetime(text: str, message_dt: datetime) -> ParsedRideTime | None:
    text = normalize_text(text)
    if not POST_TAG_RE.search(text):
        return None

    message_local = message_dt.astimezone(TZ)
    date_result = extract_date(text, message_local.date())
    if date_result is None:
        return None
    ride_date, date_text, (date_start, date_end) = date_result
    time_search_text = text[:date_start] + " " * (date_end - date_start) + text[date_end:]

    time_result = extract_time(time_search_text, ride_date)
    if not time_result:
        return None

    start, end, time_text = time_result
    return ParsedRideTime(
        trip_start=start,
        trip_end=end,
        delete_at=end + DELETE_DELAY,
        date_text=date_text,
        time_text=time_text,
    )
