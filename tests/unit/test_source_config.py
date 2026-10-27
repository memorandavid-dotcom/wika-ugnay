import pytest
import yaml

from ugnay.sources.registry import host_allowed, load_source_configs

VALID = dict(
    name="Test Directory",
    url="https://www.example.gov.ph/agencies",
    category="government_directory",
    connector_type="html_directory",
    collection_method="html_public_page",
    allowed_domains=["example.gov.ph"],
)


def write_yaml(tmp_path, sources):
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    return path


def test_valid_file_loads(tmp_path):
    configs = load_source_configs(write_yaml(tmp_path, [VALID]))
    assert len(configs) == 1 and configs[0].requests_per_minute == 10


def test_empty_sources_list_is_allowed(tmp_path):
    assert load_source_configs(write_yaml(tmp_path, [])) == []


@pytest.mark.parametrize("forbidden", [
    {"enabled": True}, {"review_status": "approved"}, {"terms_reviewed_at": "2026-01-01"},
])
def test_review_fields_cannot_be_set_in_yaml(tmp_path, forbidden):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, **forbidden}]))


def test_url_host_must_be_in_allowed_domains(tmp_path):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, "allowed_domains": ["other.gov.ph"]}]))


@pytest.mark.parametrize("bad_domain", [
    "Example.GOV.ph", "https://example.gov.ph", "example", "exa mple.ph", "example.gov.ph/path",
])
def test_malformed_domains_rejected(tmp_path, bad_domain):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, "allowed_domains": [bad_domain]}]))


def test_unknown_category_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, "category": "dark_web"}]))


def test_unknown_collection_method_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, "collection_method": "bypass_login"}]))


def test_duplicate_names_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [VALID, VALID]))


def test_non_http_url_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_source_configs(write_yaml(tmp_path, [{**VALID, "url": "ftp://www.example.gov.ph/x"}]))


@pytest.mark.parametrize("host,expected", [
    ("example.gov.ph", True),
    ("www.example.gov.ph", True),
    ("EXAMPLE.GOV.PH.", True),
    ("notexample.gov.ph", False),
    ("example.gov.ph.evil.com", False),
])
def test_host_allowed(host, expected):
    assert host_allowed(host, ["example.gov.ph"]) is expected