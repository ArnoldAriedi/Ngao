from datetime import date

import pytest

from app.categories import CATEGORIES
from app.register_rows import validate_row

TODAY = date(2026, 10, 27)
GOOD = {
    "source_reference": "C-1", "source_name": "Court", "outcome": "CONVICTED", "offense_category": "SEXUAL_ASSAULT",
    "offense_label": "Sexual assault", "judgment_date": "2022-05-10", "county": "Nairobi County",
    "area_label": "Area", "latitude": "-1.2864", "longitude": "36.8172",
}


def check(**changes):
    return validate_row({**GOOD, **changes}, CATEGORIES, TODAY)


def test_good_row_is_cleaned_and_coordinates_rounded():
    status, clean = check(convictions_count="2", release_date="2024-01-02")
    assert status == "ok"
    assert (clean["latitude"], clean["longitude"], clean["convictions_count"]) == (-1.29, 36.82, 2)
    assert clean["release_date"] == date(2024, 1, 2) and clean["sentence_description"] is None


def test_non_convictions_are_skipped_not_rejected():
    assert check(outcome="ACQUITTED")[0] == "skip"
    assert check(outcome="")[0] == "skip"


@pytest.mark.parametrize("changes", [
    {"judgment_date": "10/05/2022"},
    {"judgment_date": "2030-01-01"},
    {"judgment_date": "0202-01-01"},
    {"release_date": "2020-01-01"},
    {"convictions_count": "two"},
    {"convictions_count": "0"},
    {"convictions_count": "99"},
    {"latitude": "36.8172", "longitude": "-1.2864"},
    {"latitude": "nan"},
    {"longitude": "abc"},
    {"offense_category": "KIDNAPPING"},
    {"county": ""},
    {"offense_label": "x" * 201},
])
def test_bad_rows_are_rejected_with_a_reason(changes):
    status, why = check(**changes)
    assert status == "reject" and isinstance(why, str) and why


HEADER = ",".join(GOOD)


def write_export(directory, rows):
    path = directory / "export.csv"
    path.write_text(HEADER + "\n" + "\n".join(",".join(row.values()) for row in rows) + "\n")
    return path


def test_whole_file_is_validated_with_line_numbers_and_duplicates(tmp_path):
    from app.register_rows import read_export, write_rejects

    rows = [
        GOOD,
        {**GOOD, "source_reference": "C-2", "latitude": "36.8", "longitude": "-1.2"},
        {**GOOD, "source_reference": "C-3", "outcome": "ACQUITTED"},
        {**GOOD},
        {**GOOD, "source_reference": "C-5", "judgment_date": "soon"},
    ]
    clean, rejects, skipped = read_export(write_export(tmp_path, rows), CATEGORIES, TODAY)

    assert [row["source_reference"] for row in clean] == ["C-1"]
    assert skipped == 1
    assert [line for line, _ in rejects] == [3, 5, 6]
    assert "duplicate of line 2" in rejects[1][1]

    report = write_rejects(tmp_path / "export.csv", rejects).read_text().splitlines()
    assert report[0] == "line,reason" and len(report) == 4


def test_missing_column_stops_the_import(tmp_path):
    from app.register_rows import read_export

    path = tmp_path / "bad.csv"
    path.write_text("source_reference,outcome\nC-1,CONVICTED\n")
    with pytest.raises(SystemExit):
        read_export(path, CATEGORIES, TODAY)
