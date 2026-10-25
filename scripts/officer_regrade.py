"""Officer re-grade pack for the field-evidence questions (evals/field_evidence.json).

  python scripts/officer_regrade.py run    > docs/officer-regrade/answers-<date>.jsonl   # real agent run
  python scripts/officer_regrade.py render docs/officer-regrade/answers-<date>.jsonl      # writes .md and .html

`run` asks the agent each question with whatever draft mode is configured and records exactly what it
returned (officer draft, proposed farmer text, sources, priority). `render` turns that record into a
printable grading sheet; nothing in it is edited by hand. Print the .html to PDF with any browser, e.g.
  google-chrome --headless --no-pdf-header-footer --print-to-pdf=pack.pdf pack.html
"""
import asyncio, html, json, os, subprocess, sys, tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/regrade.db")
from agrireach import agent, evalset, knowledge, llm, voice_script  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "officer-regrade")
GRADES = ["Correct", "Partly correct", "Wrong", "Unsafe"]
APPROVE = ["Yes, as it is", "Only with edits", "No"]


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=os.path.dirname(__file__)).stdout.strip()
    except Exception:
        return "unknown"


async def run() -> None:
    print(json.dumps({"run": {"started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "commit": _commit(), "draft_mode": llm.mode(),
                              "model": os.getenv("LLM_MODEL", ""),
                              "judge": os.getenv("AGRIREACH_JUDGE_MODEL") or "off"}}))
    for e in evalset.load():
        base = {"id": e["id"], "topic": e["topic"], "question": e.get("question")}
        if e.get("skip"):
            print(json.dumps(base | {"not_run": e["skip"]}, ensure_ascii=False))
            continue
        if e.get("kind") == "voice_script":
            advisory = " ".join(f"{knowledge.reference(i)['text']} [{i}]" for i in e["advisory_passages"])
            s = voice_script.build(advisory, "[officer's name]", "maize fertilizer")
            print(json.dumps(base | {"kind": "voice_script", "advisory": advisory, "script": s.text,
                                     "seconds": s.seconds, "problems": list(s.problems)}, ensure_ascii=False))
            continue
        o = await agent.run(e["question"])
        fd = o.get("farmer_draft") or {}
        cc = o.get("citation_check") or {}
        print(json.dumps(base | {
            "status": o["status"], "priority": o["priority"], "urgent_reasons": o["urgent_reasons"],
            "clarification": o["clarification"], "draft": o["draft"], "draft_mode": o["draft_mode"],
            "sources": o["sources"], "zone": o.get("zone"), "rainfall_attached": bool((o.get("rainfall") or {}).get("available")),
            "drafts_tried": len(cc.get("attempts") or []), "check_ok": cc.get("ok"),
            "farmer_text": fd.get("text", ""), "farmer_notes": fd.get("problems", []),
            "auto_problems": evalset.grade(e, o)}, ensure_ascii=False))
    print(json.dumps({"run_end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}))


INTRO = (
    "AgriReach is a prototype that drafts answers to farmers' questions about maize and soybean from published "
    "Ghanaian extension guides (MoFA, CSIR-SARI with APNI, and IITA). It is not in use with farmers. Every draft "
    "goes to an extension officer, who edits, approves or rejects it; nothing reaches a farmer without that "
    "approval. The questions below are based on problems farmers reported in news and research. Under each one is "
    "exactly what AgriReach produced in its most recent test run, not edited. Please mark each answer correct, "
    "partly correct, wrong or unsafe, add a short comment, and say whether you would approve it as it is. Your "
    "marks decide what gets fixed next.")

HOW = [
    "**For the officer** is the draft AgriReach puts on the officer's screen. Codes in square brackets name the "
    "guide and page each sentence comes from (list at the end).",
    "**Proposed SMS to the farmer** is the plain-language text AgriReach suggests sending after approval.",
    "\"Urgent\" means AgriReach flagged the case for the officer's early attention; it does not mean the answer "
    "is urgent advice.",
    "\"I do not know.\" is what AgriReach writes when its guides do not cover the question; the officer then "
    "answers.",
]


def _load(path: str) -> tuple[dict, list[dict]]:
    meta, rows = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "run" in r:
                meta = r["run"]
            elif "run_end" in r:
                meta["finished"] = r["run_end"]
            else:
                rows.append(r)
    return meta, rows


def _answer_parts(r: dict) -> list[tuple[str, str]]:
    """(label, text) blocks showing what AgriReach returned, verbatim."""
    if "not_run" in r:
        return [("Not run", "This question has to be written by a native speaker; it was deliberately not "
                 "machine-translated, so AgriReach has no answer to grade yet. If you speak the language, please "
                 "write the question as a farmer would say it in the comment box.")]
    if r.get("kind") == "voice_script":
        return [("Approved advice it starts from (guide text)", r["advisory"]),
                ("Voice message script AgriReach builds from it (about %d seconds)" % r["seconds"], r["script"])]
    if r["status"] == "draft" and r.get("clarification"):
        return [("AgriReach's reply (it asks the farmer before drafting anything)", r["clarification"])]
    parts = [("For the officer", r["draft"])]
    if r.get("farmer_text"):
        parts.append(("Proposed SMS to the farmer", r["farmer_text"]))
    if r.get("farmer_notes"):
        parts.append(("AgriReach's note to the officer about the SMS", "; ".join(r["farmer_notes"])))
    return parts


def _flags(r: dict) -> str:
    if "not_run" in r or r.get("kind") == "voice_script" or r.get("status") == "draft":
        return ""
    bits = [f"Priority: {r['priority']}"]
    if r.get("urgent_reasons"):
        bits.append("why: " + "; ".join(r["urgent_reasons"]))
    return ". ".join(bits) + "."


def _sources_used(rows: list[dict]) -> list[str]:
    ids = sorted({p.split(":")[0] for r in rows for p in r.get("sources") or []}
                 | {p.split(":")[0].strip("[]") for r in rows if r.get("kind") == "voice_script"
                    for p in [r["advisory"].rsplit("[", 1)[-1].rstrip("]")]})
    src = knowledge.load()["sources"]
    return [f"{i}: {src[i]['title']} ({src[i]['publisher']}, {src[i]['year']})" for i in ids if i in src]


def render_md(meta: dict, rows: list[dict]) -> str:
    out = ["# AgriReach: officer re-grade sheet", "", INTRO, "",
           f"Test run: {meta.get('started', '?')} (UTC), code version {meta.get('commit', '?')}, "
           f"drafting model {meta.get('model') or meta.get('draft_mode', '?')}.", "", "How to read it:", ""]
    out += [f"- {h}" for h in HOW] + [""]
    for r in rows:
        out += [f"## {r['id']} ({r['topic']})", ""]
        out += [f"**Farmer's question:** {r['question']}" if r.get("question") else
                "**Farmer's question:** (to be written by a native speaker)", ""]
        for label, text in _answer_parts(r):
            out += [f"**{label}:**", ""] + [f"> {ln}" if ln else ">" for ln in text.split("\n")] + [""]
        if _flags(r):
            out += [f"_{_flags(r)}_", ""]
        out += ["Your grade: " + "   ".join(f"[ ] {g}" for g in GRADES), "",
                "Would you approve this as it is? " + "   ".join(f"[ ] {a}" for a in APPROVE), "",
                "Comment: ______________________________________________", ""]
    out += ["## Summary", "", "| Q | Topic | Grade (correct / partly / wrong / unsafe) | Comment | "
            "Would you approve this as it is? |", "|---|---|---|---|---|"]
    out += [f"| {r['id']} | {r['topic']} |  |  |  |" for r in rows]
    out += ["", "Officer's name (optional): __________________  District: __________________  Date: __________", "",
            "## Guides cited", ""] + [f"- {s}" for s in _sources_used(rows)] + [""]
    return "\n".join(out)


CSS = """
@page { size: A4; margin: 14mm 14mm 14mm 14mm; }
body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 9.5pt; line-height: 1.3; color: #111; }
h1 { font-size: 16pt; margin: 0 0 6pt; } h2 { font-size: 12pt; margin: 0 0 4pt; }
.q { border: 1px solid #888; padding: 6pt 8pt; margin: 0 0 8pt; }
.q h2, .label { break-after: avoid; } .grade { break-inside: avoid; }
.label { font-weight: bold; margin: 5pt 0 1pt; }
.text { white-space: pre-wrap; background: #f3f3f3; padding: 4pt 6pt; border-left: 3px solid #999; }
.flags { font-style: italic; color: #333; margin-top: 4pt; font-size: 9pt; }
.grade { margin-top: 6pt; border-top: 1px dashed #888; padding-top: 5pt; }
.box { display: inline-block; width: 10pt; height: 10pt; border: 1px solid #000; vertical-align: -1pt;
       margin: 0 3pt 0 9pt; } .box:first-child { margin-left: 0; }
.line { border-bottom: 1px solid #000; height: 16pt; }
table { border-collapse: collapse; width: 100%; break-inside: avoid; }
td, th { border: 1px solid #000; padding: 4pt; vertical-align: top; font-size: 9pt; }
td { height: 22pt; } .meta { font-size: 9pt; color: #333; } ul { margin: 3pt 0; padding-left: 14pt; }
.summary { break-before: page; }
"""


def render_html(meta: dict, rows: list[dict]) -> str:
    e = html.escape
    boxes = lambda opts: "".join(f'<span class="box"></span>{e(o)}' for o in opts)
    md_bold = lambda s: e(s).replace("**", "")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>AgriReach officer re-grade sheet</title>"
           f"<style>{CSS}</style></head><body>", "<h1>AgriReach: officer re-grade sheet</h1>",
           f"<p>{e(INTRO)}</p>",
           f"<p class='meta'>Test run {e(meta.get('started', '?'))} (UTC), code version {e(meta.get('commit', '?'))}, "
           f"drafting model {e(meta.get('model') or meta.get('draft_mode', '?'))}.</p>",
           "<ul class='meta'>" + "".join(f"<li>{md_bold(h)}</li>" for h in HOW) + "</ul>"]
    for r in rows:
        q = e(r["question"]) if r.get("question") else "<i>(to be written by a native speaker)</i>"
        out.append(f"<div class='q'><h2>{e(r['id'])} ({e(r['topic'])})</h2><div><b>Farmer's question:</b> {q}</div>")
        for label, text in _answer_parts(r):
            out.append(f"<div class='label'>{e(label)}:</div><div class='text'>{e(text)}</div>")
        if _flags(r):
            out.append(f"<div class='flags'>{e(_flags(r))}</div>")
        out.append(f"<div class='grade'><b>Your grade:</b> {boxes(GRADES)}<br><b>Would you approve this as it is?"
                   f"</b> {boxes(APPROVE)}<div style='margin-top:5pt'><b>Comment:</b></div>"
                   "<div class='line'></div></div></div>")
    out.append("<div class='summary'><h2>Summary</h2><table><tr><th>Q</th><th>Topic</th><th>Grade (correct / "
               "partly / wrong / unsafe)</th><th style='width:40%'>Comment</th><th>Would you approve this as it "
               "is?</th></tr>")
    out += [f"<tr><td>{e(r['id'])}</td><td>{e(r['topic'])}</td><td></td><td></td><td></td></tr>" for r in rows]
    out.append("</table><p>Officer's name (optional): ______________ District: ______________ "
               "Date: __________</p><h2>Guides cited</h2><ul class='meta'>"
               + "".join(f"<li>{e(s)}</li>" for s in _sources_used(rows)) + "</ul></div></body></html>")
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["run"]:
        asyncio.run(run())
    elif sys.argv[1:2] == ["render"]:
        meta, rows = _load(sys.argv[2])
        with open(os.path.join(OUT, "officer-regrade.md"), "w", encoding="utf-8") as f:
            f.write(render_md(meta, rows))
        with open(os.path.join(OUT, "officer-regrade.html"), "w", encoding="utf-8") as f:
            f.write(render_html(meta, rows))
    else:
        sys.exit(__doc__)
