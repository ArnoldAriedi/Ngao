import csv
import sys

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import AuditEntry, ConvictionRecord
from scripts import import_register
from tests.integration.helpers import make_staff, make_user, search, staff_headers

COLUMNS = [
    "source_reference", "source_name", "outcome", "offense_category", "offense_label", "judgment_date", "release_date",
    "convictions_count", "sentence_description", "county", "area_label", "latitude", "longitude",
]


def row(reference="CASE-1", **changes):
    fields = {
        "source_reference": reference, "source_name": "High Court", "outcome": "CONVICTED",
        "offense_category": "SEXUAL_ASSAULT", "offense_label": "Sexual assault", "judgment_date": "2024-03-01",
        "release_date": "", "convictions_count": "1", "sentence_description": "8 years", "county": "Nairobi County",
        "area_label": "Westlands", "latitude": "-1.2864", "longitude": "36.8172",
    }
    return {**fields, **changes}


def export(tmp_path, *rows, name="export.csv"):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow([r[column] for column in COLUMNS])
    return path


def run_import(monkeypatch, path, *flags):
    monkeypatch.setattr(sys, "argv", ["import_register", str(path), *flags])
    import_register.main()


def count(db, model=ConvictionRecord):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def test_rows_arrive_pending_with_random_ids_and_rounded_coordinates(db, monkeypatch, tmp_path, capsys):
    run_import(monkeypatch, export(tmp_path, row("A"), row("B", latitude="-1.30491")))
    records = list(db.scalars(select(ConvictionRecord).order_by(ConvictionRecord.id)))
    assert [r.publication_status for r in records] == ["PENDING", "PENDING"]
    assert all(r.public_record_id.startswith("NGA-") and len(r.public_record_id) == 14 for r in records)
    assert records[0].public_record_id != records[1].public_record_id
    assert (records[1].latitude, records[0].longitude) == (-1.3, 36.82)
    assert all(r.is_synthetic is False and r.last_verified_at is not None for r in records)
    assert "New 2" in capsys.readouterr().out


def test_every_import_is_recorded_with_the_file_name_and_a_hash(db, monkeypatch, tmp_path):
    run_import(monkeypatch, export(tmp_path, row("A"), row("B", outcome="ACQUITTED"), name="june.csv"))
    entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "RECORDS_IMPORTED"))
    assert entry.staff_id is None and "june.csv" in entry.detail
    assert "sha256=" in entry.detail and "new=1" in entry.detail and "skipped=1" in entry.detail


def test_imported_records_stay_hidden_until_an_administrator_approves_them(client, db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "demo_mode", False)
    run_import(monkeypatch, export(tmp_path, row("A", latitude="-1.2864")))
    reader = make_user(db)
    assert search(client, reader).json() == []

    admin, _ = make_staff(db, "ADMIN")
    pending = client.get("/api/v1/admin/records/pending", headers=staff_headers(admin)).json()
    approved = client.post("/api/v1/admin/records/approve", json={"record_ids": [pending[0]["id"]]}, headers=staff_headers(admin))
    assert approved.status_code == 200
    assert len(search(client, reader).json()) == 1


def test_one_bad_row_stops_everything_and_lists_the_problem(db, monkeypatch, tmp_path, capsys):
    path = export(tmp_path, row("GOOD"), row("BAD", judgment_date="next week"))
    with pytest.raises(SystemExit) as stopped:
        run_import(monkeypatch, path)
    assert "Nothing imported" in str(stopped.value)
    assert count(db) == 0 and count(db, AuditEntry) == 0
    report = (tmp_path / "export.rejected.csv").read_text().splitlines()
    assert report[0] == "line,reason" and report[1].startswith("3,") and "judgment_date" in report[1]
    assert "1 rows rejected" in capsys.readouterr().out


def test_skip_invalid_imports_the_good_rows_and_still_reports_the_rest(db, monkeypatch, tmp_path, capsys):
    path = export(tmp_path, row("GOOD"), row("BAD", latitude="36.8", longitude="-1.2"), row("GOOD"))
    run_import(monkeypatch, path, "--skip-invalid")
    assert count(db) == 1
    out = capsys.readouterr().out
    assert "2 rows rejected" in out and "rejected 2" in out
    assert (tmp_path / "export.rejected.csv").exists()


def test_a_missing_column_is_refused_before_anything_is_read(db, monkeypatch, tmp_path):
    path = tmp_path / "thin.csv"
    path.write_text("source_reference,outcome\nA,CONVICTED\n")
    with pytest.raises(SystemExit):
        run_import(monkeypatch, path)
    assert count(db) == 0


def test_importing_the_same_file_again_changes_nothing_and_keeps_the_ids(db, monkeypatch, tmp_path, capsys):
    path = export(tmp_path, row("A"))
    run_import(monkeypatch, path)
    first_id = db.scalar(select(ConvictionRecord.public_record_id))
    run_import(monkeypatch, path)
    assert count(db) == 1 and db.scalar(select(ConvictionRecord.public_record_id)) == first_id
    assert "New 0, changed 0" in capsys.readouterr().out


def test_ids_do_not_depend_on_the_app_secret(db, monkeypatch, tmp_path):
    path = export(tmp_path, row("A"))
    run_import(monkeypatch, path)
    monkeypatch.setattr(settings, "app_secret", "a-completely-different-secret-value-1234567890")
    run_import(monkeypatch, path)
    assert count(db) == 1


def test_a_changed_approved_record_goes_back_to_pending_for_review(db, monkeypatch, tmp_path, capsys):
    run_import(monkeypatch, export(tmp_path, row("A")))
    record = db.scalar(select(ConvictionRecord))
    record.publication_status = "APPROVED"
    db.commit()
    run_import(monkeypatch, export(tmp_path, row("A", offense_label="Sexual assault, amended", convictions_count="2")))
    db.expire_all()
    record = db.scalar(select(ConvictionRecord))
    assert (record.publication_status, record.offense_label, record.convictions_count) == ("PENDING", "Sexual assault, amended", 2)
    assert "1 pulled back for re-approval" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["SUSPENDED", "REMOVED"])
def test_an_import_never_revives_a_record_staff_took_down(db, monkeypatch, tmp_path, status):
    run_import(monkeypatch, export(tmp_path, row("A")))
    record = db.scalar(select(ConvictionRecord))
    record.publication_status = status
    db.commit()
    run_import(monkeypatch, export(tmp_path, row("A", offense_label="Changed label")))
    db.expire_all()
    assert db.scalar(select(ConvictionRecord.publication_status)) == status


def test_duplicate_rows_in_one_file_are_rejected_not_doubled(db, monkeypatch, tmp_path):
    path = export(tmp_path, row("A"), row("A", offense_label="Different"))
    run_import(monkeypatch, path, "--skip-invalid")
    assert count(db) == 1
    assert "duplicate of line 2" in (tmp_path / "export.rejected.csv").read_text()


def test_non_convictions_are_skipped_quietly(db, monkeypatch, tmp_path, capsys):
    run_import(monkeypatch, export(tmp_path, row("A", outcome="ACQUITTED"), row("B", outcome="PENDING_APPEAL")))
    assert count(db) == 0 and not (tmp_path / "export.rejected.csv").exists()
    assert "skipped 2" in capsys.readouterr().out


def test_the_same_reference_from_two_sources_is_two_records(db, monkeypatch, tmp_path):
    run_import(monkeypatch, export(tmp_path, row("X", source_name="High Court"), row("X", source_name="Magistrates")))
    assert count(db) == 2


def test_dates_in_the_future_are_never_imported(db, monkeypatch, tmp_path):
    with pytest.raises(SystemExit):
        run_import(monkeypatch, export(tmp_path, row("A", judgment_date="2999-01-01")))
    assert count(db) == 0
