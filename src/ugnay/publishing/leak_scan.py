"""Scan exported text for personal data. Findings never include the matched text."""
import re
from pathlib import Path

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
PHONE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
# Removed before the phone scan so timestamps and IDs are not mistaken for numbers.
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+\-Z]*)?")


def scan_text(text: str, forbidden_names=()) -> list[str]:
    findings: list[str] = []
    for match in EMAIL.finditer(text):
        findings.append(f"email-like text at offset {match.start()}")

    cleaned = _ISO_DATE.sub(" ", _UUID.sub(" ", text))
    for match in PHONE.finditer(cleaned):
        if sum(ch.isdigit() for ch in match.group()) >= 7:
            findings.append("phone-like number")

    for index, name in enumerate(forbidden_names):
        name = (name or "").strip()
        if len(name) < 3 or name == "[erased]":
            continue
        pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(f"name from contacts table (#{index}) at offset {match.start()}")
    return findings


def scan_directory(directory: Path, forbidden_names=()) -> list[str]:
    findings: list[str] = []
    for path in sorted(Path(directory).glob("*.csv")):
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path.name}: {item}" for item in scan_text(text, forbidden_names))
    return findings