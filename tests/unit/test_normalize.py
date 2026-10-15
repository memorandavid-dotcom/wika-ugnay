import pytest

from ugnay.outreach.suppression import _domain_candidates
from ugnay.processing.normalize import (
    has_valid_email_syntax,
    normalize_email,
    normalize_phone,
    normalize_url,
)


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Registrar@Example.EDU.ph ") == "registrar@example.edu.ph"


def test_normalize_email_strips_mailto_prefix():
    assert normalize_email("mailto:Info@Example.ph") == "info@example.ph"


@pytest.mark.parametrize("bad", ["no-at-sign", "a@@b.com", "@b.com", "a@"])
def test_normalize_email_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        normalize_email(bad)


def test_email_syntax_check():
    assert has_valid_email_syntax("registrar@example.edu.ph")
    assert not has_valid_email_syntax("a@b")
    assert not has_valid_email_syntax("a b@c.com")
    assert not has_valid_email_syntax("a@b..com")


def test_normalize_phone_keeps_plus_and_digits():
    assert normalize_phone("+63 (2) 8123-4567") == "+63281234567"


def test_normalize_phone_rejects_short_numbers():
    with pytest.raises(ValueError):
        normalize_phone("12345")


def test_normalize_url_lowercases_host_and_drops_fragment():
    assert (
        normalize_url("HTTPS://Example.EDU.ph/Contact?x=1#frag")
        == "https://example.edu.ph/Contact?x=1"
    )


def test_normalize_url_rejects_non_http():
    with pytest.raises(ValueError):
        normalize_url("ftp://example.ph/file")


def test_domain_candidates_stop_before_tld():
    assert _domain_candidates("a.b.edu.ph") == ["a.b.edu.ph", "b.edu.ph", "edu.ph"]
    assert _domain_candidates("example.ph") == ["example.ph"]
    assert _domain_candidates("localhost") == ["localhost"]