"""Run: python test_bot.py"""
import csv
import io
from datetime import date, datetime

from bot import TZ, day_sessions, fmt, session_window

# Trimmed copy of the real "uge 48" tab.
WEEK_48 = """BabyDillars,Team Schedule,,,,,,,Colors
,Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday,Players
Klokken 17-18,Sørensen,Official,Sørensen,,,tAOUNTED,træning,
Klokken 18-19,Bobby,Official,Sørensen,træning,,tAOUNTED,,
Klokken 19-20,Bobby,træning,træning,træning,,Bobby,,
Klokken 20-21,Bobby,træning,træning,Træning,,Bobby,,
Klokken 21-22,Bobby,,træning,,,Bobby,,
Klokken 22-23,Bobby,træning,,,,,,
Klokken 23-24,Sørensen,Sørensen,Sørensen,Sørensen,,,Sørensen,
Klokken 24-01,Sørensen,Sørensen,Sørensen,Sørensen,,,træning,
,23/11,24/11,25/11,26/11,27/11,28/11,29/11,
,,,,,,,mac på europa,
"""
TEMPLATE = WEEK_48.split(",23/11")[0].rsplit("\n", 1)[0]  # no date row, like the fallback tab
rows = lambda s: list(csv.reader(io.StringIO(s)))
day = lambda d: [fmt(s) for s in day_sessions(rows(WEEK_48), d)]

assert day(date(2026, 11, 23)) == []
assert day(date(2026, 11, 24)) == [
    "Klokken 17-19 - Official", "Klokken 19-21 - Træning", "Klokken 22-23 - Træning"]
assert day(date(2026, 11, 25)) == ["Klokken 19-22 - Træning"]
assert day(date(2026, 11, 26)) == ["Klokken 18-21 - Træning"]
assert day(date(2026, 11, 29)) == ["Klokken 17-18 - Træning", "Klokken 24-01 - Træning"]
assert day_sessions(rows(WEEK_48), date(2027, 11, 24)) is None  # same weekday, wrong date
assert day_sessions(rows(TEMPLATE), date(2026, 11, 25)) is None

wed = date(2026, 11, 25)
assert session_window(wed, ("19", "22", "Træning")) == (datetime(2026, 11, 25, 19, tzinfo=TZ), datetime(2026, 11, 25, 22, tzinfo=TZ))
assert session_window(wed, ("23", "01", "Træning")) == (datetime(2026, 11, 25, 23, tzinfo=TZ), datetime(2026, 11, 26, 1, tzinfo=TZ))
assert session_window(wed, ("24", "01", "Træning"))[0] == datetime(2026, 11, 26, 0, tzinfo=TZ)
print("ok")
