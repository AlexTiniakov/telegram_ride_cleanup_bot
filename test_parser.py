from datetime import datetime
from zoneinfo import ZoneInfo

from parser import parse_ride_datetime

TZ = ZoneInfo("Europe/Kyiv")
REF = datetime(2026, 9, 25, 15, 30, tzinfo=TZ)

CASES = [
    ("#Водій\n26.09.26 субота, ранок\n07:45 +/-\nБілки - Борова", "2026-09-26T07:50"),
    ("#Водій , 25.09\nВднг-Борова.\n17:30\n130", "2026-09-25T17:35"),
    ("#водій 25/09/2026 16:30-40", "2026-09-25T16:45"),
    ("#Пасажир 25-09-26 16: 30-17:00", "2026-09-25T17:05"),
    ("#Пасажир 25.09.2026 16.30 – 17.00", "2026-09-25T17:05"),
    ("#водитель 25 сентября 2026 7:05", "2026-09-25T07:10"),
    ("#водій 26 вересня 07.45", "2026-09-26T07:50"),
    ("#водій 26.09 7-45", "2026-09-26T07:50"),
    ("#водій 26.09 7 год 45 хв", "2026-09-26T07:50"),
    ("#водій 26.09 23:30-00:15", "2026-09-27T00:20"),
    ("#водій 26.09 16:50-10", "2026-09-26T17:15"),
    # Regression: year in a dotted date must not be mistaken for time.
    ("#водій 25.09.26 07:45", "2026-09-25T07:50"),
]

for text, expected_prefix in CASES:
    parsed = parse_ride_datetime(text, REF)
    assert parsed is not None, text
    actual = parsed.delete_at.isoformat(timespec="minutes")
    assert actual.startswith(expected_prefix), (text, actual, expected_prefix)
    print("OK", repr(text.replace("\n", " | ")), "->", actual)


# Undated and relative-only announcements no longer satisfy the rules.
for text in ("#Водій 07.05", "#Водій 17:30", "#Водій завтра 07:00",
             "#Водій сьогодні 17:30", "#Водій 07.05–08.10",
             "#Водій 31.02.2026 17:30", "#Водій 32.10 17:30",
             "#Водій 06.10.", "#Водій 06,10,2026"):
    assert parse_ride_datetime(text, REF) is None, text

for date_text in ("06.10", "6.10.", "06,10", "06,10,", "06.10,2026",
                  "06,10.26", "06/10/2026", "06-10-26", "6 жовтня",
                  "06 . 10 .", "06, 10, 2026."):
    text = f"#пасажир\n{date_text}\n7:30 - 8:00"
    parsed = parse_ride_datetime(text, datetime(2026,10,5,17,tzinfo=TZ))
    assert parsed is not None, text
    assert parsed.delete_at.isoformat() == "2026-10-06T08:05:00+03:00", (text, parsed)

parsed = parse_ride_datetime("#Водій 02.01 07:00", datetime(2026,12,31,17,tzinfo=TZ))
assert parsed.delete_at.isoformat() == "2027-01-02T07:05:00+02:00"
print("OK: required dates, punctuation, no year, invalid dates and year rollover")
