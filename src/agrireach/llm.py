"""Draft writer. Uses an open-weights model behind any OpenAI-compatible endpoint when
LLM_BASE_URL and LLM_MODEL are set; otherwise a deterministic OFFLINE STUB (no model)."""
from __future__ import annotations

import os

STUB_LABEL = "[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]"

SYSTEM = (
    "You are AgriReach, drafting advice for a Ghanaian extension officer to review (never sent directly to a farmer). "
    "Use ONLY the numbered passages provided. Cite with one passage id per bracket, e.g. [ID], right after the words "
    "it supports. Every number and date you write must be copied exactly from the passage you cite right after it; "
    "never add, round, merge or move figures between passages. "
    "If a CONFLICTS section is given, the sources disagree: state each source's figure in its own sentence with only "
    "that source's citation, do not pick one, do not merge them into one range, and do not count sources "
    "(never write 'two sources say'). Say the officer should choose. "
    "If the passages do not answer the question, say you do not know. "
    "Never prescribe pesticide/herbicide products or doses and never confirm a disease diagnosis. "
    "Write in English for the officer. Plain language, at most 150 words."
)


def mode() -> str:
    return "llm" if os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL") else "stub"


def stub_draft(question: str, passages: list[dict], notes: list[str]) -> str:
    lines = [STUB_LABEL]
    if not passages:
        lines.append("I could not find guidance on this in the curated sources, so I cannot give a grounded answer. "
                     "An extension officer needs to answer this case.")
    else:
        lines.append("What the curated sources say:")
        for p in passages:
            lines.append(f'- "{p["text"]}" [{p["id"]}]')
    lines += [f"Note: {n}" for n in notes]
    return "\n".join(lines)


def _conflict_block(conflicts: dict | None) -> str:
    if not conflicts:
        return ""
    lines = ["CONFLICTS (detected by code; show every side separately):"]
    for key, group in conflicts.items():
        lines.append(f"- {key.replace('_', ' ')}: " + " | ".join(f"[{p['id']}] says: \"{p['text']}\"" for p in group))
    return "\n".join(lines) + "\n\n"


def draft(question: str, passages: list[dict], notes: list[str], conflicts: dict | None = None,
          feedback: list[str] | None = None) -> tuple[str, str]:
    """Returns (text, mode_used). `feedback` lists citation-check problems from a previous attempt."""
    if mode() == "stub":
        return stub_draft(question, passages, notes), "stub"
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    ctx = "\n".join(f"[{p['id']}] {p['text']}" for p in passages) or "(no passages found)"
    msg = (f"Farmer question: {question}\n\nPassages:\n{ctx}\n\n{_conflict_block(conflicts)}"
           f"Reviewer notes: {'; '.join(notes) or 'none'}")
    if feedback:
        msg += ("\n\nYour previous draft failed the automatic citation check:\n- " + "\n- ".join(feedback) +
                "\nRewrite it so every figure is copied from the passage cited right after it, and every conflict "
                "side is stated with its own citation.")
    r = client.chat.completions.create(model=os.environ["LLM_MODEL"], temperature=0,
                                       messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}])
    return r.choices[0].message.content.strip(), f"llm:{os.environ['LLM_MODEL']}"
