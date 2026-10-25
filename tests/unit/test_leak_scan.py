from ugnay.publishing.leak_scan import scan_directory, scan_text


def test_scanner_detects_planted_personal_data(tmp_path):
    (tmp_path / "bad.csv").write_text(
        "name,contact\nOrg,someone@example.ph\nOrg2,+63 917 123 4567\nOrg3,Juan Dela Cruz\n",
        encoding="utf-8",
    )
    findings = " ".join(scan_directory(tmp_path, ["Juan Dela Cruz"]))
    assert "email" in findings
    assert "phone" in findings
    assert "name" in findings


def test_scanner_ignores_dates_uuids_years_and_domains():
    text = (
        "2026-10-16T19:09:00+09:00,984e8b88-0be3-401e-a583-a1a80ad75e20,"
        "1998,2026-10-16 19:09:00.123456+00:00,https://example.edu.ph/a"
    )
    assert scan_text(text) == []


def test_name_match_respects_word_boundaries():
    assert scan_text("Banana Republic", ["Ana"]) == []
    assert scan_text("Ana Reyes works here", ["Ana"]) != []