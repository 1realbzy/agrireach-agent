"""Unit tests for the code citation check (every date/number in a draft must be in its cited passage)."""
import pytest

from agrireach.citation_check import check_draft, extract_figures

P = lambda pid, src, text: {"id": pid, "source_id": src, "text": text}
WIN_A = P("APNI-SARI-2023:p11-planting-window", "APNI-SARI-2023",
          "Soybean planting in the northern region should be done between mid-June and late July based on the onset of the rains and the variety.")
WIN_B = P("IITA-SSPING-2022:p18-planting-window", "IITA-SSPING-2022",
          "The best planting time for soyabean is between mid-June to mid-July with the rains likely well established.")
MOIST = P("IITA-SSPING-2022:p18-moisture", "IITA-SSPING-2022",
          "Do not plant too early before the rains are well established as a prolonged dry spell after planting may cause the plants to die.")
DEPTH_A = P("APNI-SARI-2023:p11-depth", "APNI-SARI-2023",
            "To achieve the desired spacing, make planting holes that are about 5 cm deep at a spacing of 15 cm between holes.")
SEED = P("S:seed", "S", "The recommended seed rate is about 50 to 60 kg per hectare and 2.5 kg per plot, for 1,000 plants.")
DATE = P("D:date", "D", "Sow on 15 March in the south.")
HARV = P("APNI-SARI-2023:harvest", "APNI-SARI-2023",
         "Soybean should be harvested when 9 out of 10 pods are mature (brown in color or dry).")
CONFLICT = {"planting_window": [WIN_A, WIN_B]}


def vals(s):
    return [(f.value, f.unit) for f in extract_figures(s)]


@pytest.mark.parametrize("text,expected", [
    ("2.5 cm", [("2.5", "cm")]),
    ("50kg", [("50", "kg")]),
    ("1,000 plants", [("1000", "")]),
    ("15 March", [("15 march", "")]),
    ("March 15", [("15 march", "")]),
    ("15th of March", [("15 march", "")]),
    ("mid-June to late July", [("mid june", ""), ("late july", "")]),
    ("50 to 60 kg", [("50", "kg"), ("60", "kg")]),
    ("40 – 45 kg", [("40", "kg"), ("45", "kg")]),
    ("two weeks", [("2", "week")]),
    ("the pods may shatter", []),       # 'may' the verb is not a month
    ("one source says", []),            # counting sources is not an advice figure
])
def test_extract_formats(text, expected):
    assert vals(text) == expected


@pytest.mark.parametrize("draft", [
    "Use about 50kg per hectare [S:seed].",
    "Use 50 to 60 kg per hectare [S:seed].",
    "Use 2.5 kg per plot [S:seed].",
    "Aim for 1,000 plants [S:seed].",
    "Aim for 1000 plants [S:seed].",
])
def test_numbers_present_pass(draft):
    assert check_draft(draft, [SEED]).ok


@pytest.mark.parametrize("draft,bad", [
    ("Use about 70 kg per hectare [S:seed].", "70 kg"),
    ("Use 2.0 kg per plot [S:seed].", "2.0 kg"),
    ("Use 50 cm rows [S:seed].", "50 cm"),            # right number, wrong unit
    ("Aim for 10,000 plants [S:seed].", "10,000"),
])
def test_numbers_absent_fail(draft, bad):
    r = check_draft(draft, [SEED])
    assert not r.ok and any(bad in p for p in r.problems)


@pytest.mark.parametrize("draft,ok", [
    ("Sow on 15 March [D:date].", True),
    ("Sow on March 15 [D:date].", True),
    ("Sow on 16 March [D:date].", False),
    ("Sow on 15 April [D:date].", False),
])
def test_dates(draft, ok):
    assert check_draft(draft, [DATE]).ok is ok


def test_figure_with_no_citation_fails():
    r = check_draft("Plant 5 cm deep.", [DEPTH_A])
    assert not r.ok and "no citation" in r.problems[0]


def test_unknown_citation_fails():
    assert not check_draft("Plant 5 cm deep [MADE-UP:1].", [DEPTH_A]).ok


def test_figure_attributed_to_wrong_passage_fails():
    # 'mid-July' is in IITA, not in APNI-SARI: citing APNI-SARI for it is a misattribution.
    r = check_draft("Plant between mid-June and mid-July [APNI-SARI-2023:p11-planting-window].", [WIN_A, WIN_B])
    assert not r.ok and any("mid-July" in p for p in r.problems)


def test_citation_after_several_sentences_covers_them():
    # Real task-1 LLM draft: one citation at the end of the paragraph.
    d = ("Harvest your soybean when 9 out of 10 pods are mature, which means they are brown in color or dry. "
         "If you leave the crop in the field too long, the pods may shatter [APNI-SARI-2023:harvest].")
    assert check_draft(d, [HARV]).ok


# --- Real failing LLM drafts from docs/eval-run.txt (13 Oct 2026), replayed offline ---

TASK11_DRAFT = ("For Wa, plant soybeans between mid-June and mid-July. Ensure rains are well established to avoid plant "
                "death from dry spells [APNI-SARI-2023:p11-planting-window, IITA-SSPING-2022:p18-planting-window, "
                "IITA-SSPING-2022:p18-moisture]. Do not plant too early. Make holes 5 cm deep, spaced 15 cm apart "
                "[APNI-SARI-2023:p11-depth].")
TASK10_DRAFT = ("The planting window for soybeans in Kumasi may differ from the northern region. Two sources suggest "
                "planting between mid-June and mid-July, but one says up to late July [APNI-SARI-2023:p11-planting-window, "
                "IITA-SSPING-2022:p18-planting-window]. Plant when rains are well established to avoid dry spells that could "
                "harm young plants [IITA-SSPING-2022:p18-moisture].")


def test_task11_collapsed_conflict_fails():
    r = check_draft(TASK11_DRAFT, [WIN_A, MOIST, DEPTH_A, WIN_B], CONFLICT)
    assert not r.ok
    assert any("conflict on planting window" in p and "APNI-SARI-2023:p11-planting-window" in p for p in r.problems)


def test_task10_merged_attribution_fails():
    r = check_draft(TASK10_DRAFT, [WIN_A, MOIST, DEPTH_A, WIN_B], CONFLICT)
    assert not r.ok and any("conflict on planting window" in p for p in r.problems)


def test_conflict_shown_per_source_passes():
    d = ("APNI-SARI says plant between mid-June and late July [APNI-SARI-2023:p11-planting-window]. "
         "IITA says mid-June to mid-July [IITA-SSPING-2022:p18-planting-window]. The officer should choose. "
         "Do not plant before the rains are well established [IITA-SSPING-2022:p18-moisture].")
    assert check_draft(d, [WIN_A, MOIST, WIN_B], CONFLICT).ok


def test_task4_real_draft_passes():
    a = P("APNI-SARI-2023:p11-spacing", "APNI-SARI-2023",
          "The recommended plant spacing for soybean in northern Ghana is a row to row spacing of 50 cm and 15 cm spacing between plants in a row.")
    b = P("IITA-SSPING-2022:p17-spacing", "IITA-SSPING-2022",
          "This will allow the recommended spacing of 50 cm between rows and 10 cm between plants within the rows.")
    d = ("For soybean planting in Tamale, use a row-to-row spacing of 50 cm. For spacing between plants in a row, choose "
         "either 15 cm [APNI-SARI-2023:p11-spacing] or 10 cm [IITA-SSPING-2022:p17-spacing]. Both are recommended.")
    assert check_draft(d, [a, b], {"plant_spacing": [a, b]}).ok


# --- Bound words: a limit is part of the figure ("not deeper than 5 cm" is not "5 cm") ---

DEPTH_B = P("IITA-SSPING-2022:p18-depth", "IITA-SSPING-2022",
            "Avoid deeper sowing (recommended depth = 3 cm; not deeper than 5 cm) as this may result in loss of seed "
            "vigor and poor germination or failure to germinate.")
# Real draft, 23 Oct run A, task 11 (docs/eval-run-2026-10-23.txt): right figures, bounds swapped.
RUN_A_WA_DEPTH = "Plant seeds at 5 cm deep [APNI-SARI-2023:p11-depth], or up to 5 cm but not deeper than 3 cm [IITA-SSPING-2022:p18-depth]."


def bounds(s):
    return [(f.value, f.unit, f.bound) for f in extract_figures(s)]


@pytest.mark.parametrize("text,expected", [
    ("recommended depth = 3 cm; not deeper than 5 cm", [("3", "cm", ""), ("5", "cm", "max")]),
    ("up to 5 cm", [("5", "cm", "max")]),
    ("at most 5 cm", [("5", "cm", "max")]),
    ("a maximum of 5 cm", [("5", "cm", "max")]),
    ("do not plant deeper than 5 cm", [("5", "cm", "max")]),
    ("less than 5 cm", [("5", "cm", "max")]),
    ("at least 50 kg", [("50", "kg", "min")]),
    ("no less than 50 kg", [("50", "kg", "min")]),
    ("more than 3 weeks", [("3", "week", "min")]),
    ("50 kg or more", [("50", "kg", "min")]),
    ("3 weeks or less", [("3", "week", "max")]),
    ("50 to 60 kg", [("50", "kg", ""), ("60", "kg", "")]),       # a range is not a bound
    ("ideally 3 cm, not deeper than 5 cm", [("3", "cm", ""), ("5", "cm", "max")]),
    ("not deeper than 3 cm. Use 5 cm", [("3", "cm", "max"), ("5", "cm", "")]),  # bound does not cross a sentence
])
def test_bound_extraction(text, expected):
    assert bounds(text) == expected


def test_flipped_bounds_real_run_a_draft_fails():
    r = check_draft(RUN_A_WA_DEPTH, [DEPTH_A, DEPTH_B])
    assert not r.ok
    assert r.problems == ["'3 cm' states 3 cm as an upper limit, but the cited passage(s) "
                          "['IITA-SSPING-2022:p18-depth'] give(s) it as a plain value"]


@pytest.mark.parametrize("draft,ok", [
    ("Recommended 3 cm, not deeper than 5 cm [IITA-SSPING-2022:p18-depth].", True),
    ("Plant up to 5 cm deep; 3 cm is recommended [IITA-SSPING-2022:p18-depth].", True),
    ("Plant 5 cm deep [IITA-SSPING-2022:p18-depth].", False),          # a maximum stated as the recommendation
    ("Plant at least 3 cm deep [IITA-SSPING-2022:p18-depth].", False),  # a bound the source does not give
    ("Plant at least 5 cm deep [IITA-SSPING-2022:p18-depth].", False),  # max turned into min
])
def test_bounds_must_match_source(draft, ok):
    assert check_draft(draft, [DEPTH_B]).ok is ok


def test_every_corpus_passage_passes_when_quoted_with_its_own_citation():
    # Guards against false positives: the verbatim source text must always pass its own check.
    import json
    from pathlib import Path
    kb = json.loads((Path(__file__).resolve().parents[1] / "data" / "knowledge.json").read_text())
    for p in kb["passages"]:
        r = check_draft(f"{p['text']} [{p['id']}]", [p])
        assert r.ok, (p["id"], r.problems)
