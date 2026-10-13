"""Draft writer. Uses an open-weights model behind any OpenAI-compatible endpoint when
LLM_BASE_URL and LLM_MODEL are set; otherwise a deterministic OFFLINE STUB (no model)."""
from __future__ import annotations

import os

STUB_LABEL = "[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]"

SYSTEM = (
    "You are AgriReach, drafting advice for a Ghanaian extension officer to review (never sent directly to a farmer). "
    "Use ONLY the numbered passages provided. Cite each statement with its passage id in square brackets. "
    "If passages disagree, say so and show both. If the passages do not answer the question, say you do not know. "
    "Never prescribe pesticide/herbicide products or doses and never confirm a disease diagnosis. "
    "Plain language, at most 120 words."
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


def draft(question: str, passages: list[dict], notes: list[str]) -> tuple[str, str]:
    """Returns (text, mode_used)."""
    if mode() == "stub":
        return stub_draft(question, passages, notes), "stub"
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    ctx = "\n".join(f"[{p['id']}] {p['text']}" for p in passages) or "(no passages found)"
    msg = f"Farmer question: {question}\n\nPassages:\n{ctx}\n\nReviewer notes: {'; '.join(notes) or 'none'}"
    r = client.chat.completions.create(model=os.environ["LLM_MODEL"], temperature=0,
                                       messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}])
    return r.choices[0].message.content.strip(), f"llm:{os.environ['LLM_MODEL']}"
