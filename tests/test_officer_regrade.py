"""The officer re-grade sheet shows AgriReach's recorded answers verbatim, with a grading box for each."""
import importlib.util, json, os, re

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("officer_regrade", os.path.join(ROOT, "scripts", "officer_regrade.py"))
og = importlib.util.module_from_spec(spec)
spec.loader.exec_module(og)

ROWS = [
    {"run": {"started": "2026-10-25T17:00:00Z", "commit": "abc1234", "draft_mode": "llm", "model": "m"}},
    {"id": "F1", "topic": "Pests", "question": "Worms <in> my maize?", "status": "pending_review",
     "priority": "urgent", "urgent_reasons": ["disease or pest terms in question"], "clarification": "",
     "draft": "Scout weekly [APNI-SARI-2023-MAIZE:p18-scouting].", "sources": ["APNI-SARI-2023-MAIZE:p18-scouting"],
     "farmer_text": "Check your field once a week.", "farmer_notes": ["sources differ: edit to keep only one"]},
    {"id": "F3", "topic": "Weather", "question": "No rain. Fertiliser now?", "status": "draft", "priority": "routine",
     "urgent_reasons": [], "clarification": "Which crop is this about?", "draft": "Which crop is this about?",
     "sources": [], "farmer_text": "", "farmer_notes": []},
    {"id": "F12", "topic": "Language", "question": None, "not_run": "PLACEHOLDER"},
    {"id": "F14", "topic": "Language", "question": "Voice script.", "kind": "voice_script",
     "advisory": "Top dress when moist. [APNI-SARI-2023-MAIZE:p13-topdress-moisture]", "script": "Hello. This is AgriReach.",
     "seconds": 36, "problems": []},
    {"run_end": "2026-10-25T17:01:00Z"},
]


def _pack(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in ROWS), encoding="utf-8")
    meta, rows = og._load(str(p))
    return meta, rows, og.render_md(meta, rows), og.render_html(meta, rows)


def test_every_question_has_its_recorded_answer_and_a_grading_box(tmp_path):
    meta, rows, md, html = _pack(tmp_path)
    assert [r["id"] for r in rows] == ["F1", "F3", "F12", "F14"] and meta["commit"] == "abc1234"
    for text in ("Scout weekly [APNI-SARI-2023-MAIZE:p18-scouting].", "Check your field once a week.",
                 "sources differ: edit to keep only one", "Which crop is this about?", "Hello. This is AgriReach."):
        assert text in md and text in html
    assert md.count("Would you approve this as it is?") == len(rows) + 1  # one per question + summary column
    for g in ("Correct", "Partly correct", "Wrong", "Unsafe"):
        assert md.count(f"[ ] {g}") == len(rows) and html.count(f"</span>{g}") == len(rows)
    for qid in ("F1", "F3", "F12", "F14"):
        assert re.search(rf"^\| {qid} \|", md, re.M) and f"<td>{qid}</td>" in html


def test_not_run_questions_say_so_and_html_is_escaped(tmp_path):
    _, _, md, html = _pack(tmp_path)
    assert "native speaker" in md and "has no answer to grade yet" in md
    assert "Worms &lt;in&gt; my maize?" in html and "Worms <in>" not in html


def test_intro_makes_no_deployment_claim():
    intro = og.INTRO.lower()
    assert "not in use with farmers" in intro and "approval" in intro
    for claim in ("deployed", "is used by", "in use by", "piloted", "farmers use agrireach", "live service"):
        assert claim not in intro
