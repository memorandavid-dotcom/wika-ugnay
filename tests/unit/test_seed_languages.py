import csv

import pytest

from ugnay.jobs.seed_languages import load_languages

FIELDS = ["ID", "Name", "Macroarea", "Latitude", "Longitude", "Glottocode",
          "ISO639P3code", "Level", "Countries", "Family_ID", "Language_ID"]


def write_csv(path, records):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="")
        writer.writeheader()
        writer.writerows(records)


def test_load_filters_by_country_level_and_iso(tmp_path):
    path = tmp_path / "languages.csv"
    write_csv(path, [
        dict(ID="aust1307", Name="Austronesian", Glottocode="aust1307", Level="family"),
        dict(ID="fili1244", Name="Filipino", Glottocode="fili1244", ISO639P3code="fil",
             Level="language", Countries="PH", Family_ID="aust1307"),
        dict(ID="cebu1242", Name="Cebuano", Glottocode="cebu1242", ISO639P3code="ceb",
             Level="language", Countries="PH", Family_ID="aust1307"),
        dict(ID="manh1111", Name="Manila Tagalog", Level="dialect", Countries="PH",
             Family_ID="aust1307"),
        dict(ID="nois1234", Name="No Code Language", Level="language", Countries="PH",
             Family_ID="aust1307"),
        dict(ID="indo1234", Name="Indonesian", ISO639P3code="ind", Level="language",
             Countries="ID", Family_ID="aust1307"),
        dict(ID="dupe1234", Name="Cebuano Duplicate", ISO639P3code="ceb", Level="language",
             Countries="PH", Family_ID="aust1307"),
    ])
    rows, stats = load_languages(path)

    assert {row.iso639_3 for row in rows} == {"fil", "ceb"}
    assert next(r for r in rows if r.iso639_3 == "fil").family == "Austronesian"
    assert stats.scanned == 7
    assert stats.matched_country == 4
    assert stats.skipped_no_iso == 1
    assert stats.skipped_duplicate == 1
    assert stats.rows == 2


def test_load_rejects_file_with_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("ID,Name\nx,y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing expected columns"):
        load_languages(path)