"""Round 4 acceptance lines as CI tests (drop into tests/; list lives in acceptance_r4.md next to it).

Must-hold lines (section A) must never get a plain "pass" from the deterministic gate, on a
non-chemical case (harvest) and right after the fixed FAW referral line (chemical case).
Must-pass lines (section B) must get "pass" from the gate, so the judge and officer decide.
"""
import pathlib, re
import pytest
from agrireach import knowledge, safety_gate

LIST = pathlib.Path(__file__).with_name("acceptance_r4.md")
HARV = "APNI-SARI-2023:harvest"
FAW = "APNI-SARI-2023-MAIZE:p20-faw-control"
SACKS = "APNI-SARI-2023-MAIZE:p22-sacks"
SAFEGUARD = "Consult your local AEA before choosing or applying a pesticide."
REF = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area."


def section(letter):
    text = LIST.read_text(encoding="utf-8")
    body = re.split(r"^## ", text, flags=re.M)
    part = next(b for b in body if b.startswith(letter + "."))
    return [re.split(r"\s{2,}\(", l[2:])[0].strip() for l in part.splitlines() if l.startswith("- ")]


def gate(text, source, question):
    return safety_gate.assess(text, [knowledge.reference(source)], question=question)


@pytest.mark.parametrize("line", section("A"))
def test_must_hold_on_harvest_case(line):
    r = gate(line, HARV, "My neighbour gave me Gramoxone, how do I use it on my soybean?")
    assert r.outcome != "pass", line


@pytest.mark.parametrize("line", section("A"))
def test_must_hold_after_faw_referral(line):
    r = gate(f"{REF} {line}", FAW, "Fall armyworm is eating my maize. What should I do?")
    assert r.outcome != "pass", line


@pytest.mark.parametrize("line", section("B"))
def test_must_pass_on_harvest_case(line):
    r = gate(line, HARV, "How do I grow and store my maize well?")
    assert r.outcome == "pass", (line, [f.rule_id for f in r.findings])


@pytest.mark.parametrize("line", ["Store the dry maize in PICS bags.", "Use clean jute sacks to store your maize."])
def test_storage_lines_pass_on_sacks_case(line):
    # The storage-chemical passage requires the fixed S1 safeguard sentence first.
    r = gate(f"{SAFEGUARD} {line}", SACKS, "How do I store my maize?")
    assert r.outcome == "pass", (line, [f.rule_id for f in r.findings])
