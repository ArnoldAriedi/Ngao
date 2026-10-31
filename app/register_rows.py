import csv
from datetime import date
from pathlib import Path

from app.geo import KENYA_LATITUDE, KENYA_LONGITUDE

EARLIEST_JUDGMENT = date(1963, 12, 12)
MAX_CONVICTIONS = 20
REQUIRED = (
    "source_reference", "source_name", "outcome", "offense_category", "offense_label",
    "judgment_date", "county", "area_label", "latitude", "longitude",
)
TEXT_LIMITS = {
    "source_reference": 120, "source_name": 160, "offense_label": 200,
    "county": 100, "area_label": 120, "sentence_description": 300,
}


def parse_day(text: str, label: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{label} is not a YYYY-MM-DD date") from None


def in_range(text: str, label: str, bounds: tuple[float, float]) -> float:
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"{label} is not a number") from None
    if not bounds[0] <= number <= bounds[1]:
        raise ValueError(f"{label} {text} is outside Kenya (latitude and longitude swapped?)")
    return round(number, 2)


def validate_row(export_row: dict, categories: dict, today: date) -> tuple[str, dict | str]:
    """('ok', clean row), ('skip', why) for non-convictions, or ('reject', why)."""
    fields = {key: (export_row.get(key) or "").strip() for key in (*REQUIRED, "sentence_description", "convictions_count", "release_date")}
    if fields["outcome"] != "CONVICTED":
        return "skip", f"outcome is {fields['outcome'] or 'blank'}"
    blank = [key for key in REQUIRED if not fields[key]]
    if blank:
        return "reject", f"missing {', '.join(blank)}"
    if fields["offense_category"] not in categories:
        return "reject", f"unknown offense_category {fields['offense_category']}"
    too_long = [key for key, limit in TEXT_LIMITS.items() if len(fields[key]) > limit]
    if too_long:
        return "reject", f"{', '.join(too_long)} too long"

    try:
        judgment_date = parse_day(fields["judgment_date"], "judgment_date")
        release_date = parse_day(fields["release_date"], "release_date") if fields["release_date"] else None
        count = int(fields["convictions_count"] or 1)
        latitude = in_range(fields["latitude"], "latitude", KENYA_LATITUDE)
        longitude = in_range(fields["longitude"], "longitude", KENYA_LONGITUDE)
    except ValueError as problem:
        return "reject", str(problem)

    if not EARLIEST_JUDGMENT <= judgment_date <= today:
        return "reject", f"judgment_date {judgment_date} is before independence or in the future"
    if release_date and release_date < judgment_date:
        return "reject", "release_date is before judgment_date"
    if not 1 <= count <= MAX_CONVICTIONS:
        return "reject", f"convictions_count must be 1 to {MAX_CONVICTIONS}"

    return "ok", {
        "source_reference": fields["source_reference"],
        "source_name": fields["source_name"],
        "offense_category": fields["offense_category"],
        "offense_label": fields["offense_label"],
        "convictions_count": count,
        "judgment_date": judgment_date,
        "release_date": release_date,
        "sentence_description": fields["sentence_description"] or None,
        "county": fields["county"],
        "area_label": fields["area_label"],
        "latitude": latitude,
        "longitude": longitude,
    }


def read_export(path: Path, categories: dict, today: date):
    clean_rows, rejects, skipped, first_seen = [], [], 0, {}
    with open(path, newline="", encoding="utf-8") as export_file:
        reader = csv.DictReader(export_file)
        missing = set(REQUIRED) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Missing columns: {', '.join(sorted(missing))}")
        for line, export_row in enumerate(reader, start=2):
            status, outcome = validate_row(export_row, categories, today)
            if status == "skip":
                skipped += 1
                continue
            if status == "reject":
                rejects.append((line, outcome))
                continue
            key = (outcome["source_name"], outcome["source_reference"])
            if key in first_seen:
                rejects.append((line, f"duplicate of line {first_seen[key]}"))
                continue
            first_seen[key] = line
            clean_rows.append(outcome)
    return clean_rows, rejects, skipped


def write_rejects(path: Path, rejects: list[tuple[int, str]]) -> Path:
    rejects_path = path.with_suffix(".rejected.csv")
    with open(rejects_path, "w", newline="", encoding="utf-8") as rejects_file:
        writer = csv.writer(rejects_file, lineterminator="\n")
        writer.writerow(["line", "reason"])
        writer.writerows(rejects)
    return rejects_path
