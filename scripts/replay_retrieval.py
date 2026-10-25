#!/usr/bin/env python
# Usage: PYTHONPATH=src python scripts/replay_retrieval.py out.json  (offline stub mode; diff two outputs)
"""Offline replay: every distinct question from recorded eval runs (docs/eval-run*.txt) through the agent in stub mode;
prints sources, priority and clarification so before/after retrieval can be diffed."""
import asyncio, glob, json, sys
from agrireach import agent
qs = []
for f in sorted(glob.glob("docs/eval-run*.txt")):
    for l in open(f):
        if l.startswith("{"):
            try: o = json.loads(l)
            except Exception: continue
            q = o.get("q") or o.get("question")
            if q and q not in qs: qs.append(q)
extra = ["When should I top dress my maize?", "When should I top dress my maize in Tamale?",
         "When is top-dressing done for maize in Tamale?", "Bere bɛn na ɛsɛ sɛ medua aburo wɔ Tamale?",
         "When do I plant aburo in Tamale?"]
out = {}
for q in qs + extra:
    o = asyncio.run(agent.run(q, use_fetch=False))
    out[q] = {"sources": o["sources"], "priority": o["priority"], "clar": bool(o["clarification"]), "crop": o["crop"]}
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(len(out), "questions")
