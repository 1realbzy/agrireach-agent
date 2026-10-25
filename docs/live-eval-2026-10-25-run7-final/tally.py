import sqlite3, re, json
c = sqlite3.connect('/tmp/apprun7/main/t.db')
rows = list(c.execute("select id,case_id,actor,args,result_summary from tool_log where tool='model_usage' order by id"))
tot = 0.0; ok = att = 0; unknown = 0; errs = []; by = {}
for i, cid, actor, args, s in rows:
    a = json.loads(args); ok += a.get("calls", 0); att += a.get("attempted", 0); errs += a.get("errors", [])
    x = a.get("cost_usd")
    if x is None: unknown += 1
    else: tot += x
    k = "graded" if cid <= 11 else "concurrency"; k += "/" + ("officer" if actor.startswith("officer") else "agent")
    b = by.setdefault(k, [0.0, 0, 0]); b[0] += x or 0; b[1] += a.get("calls", 0); b[2] += a.get("attempted", 0)
print("rows", len(rows), "total $%.6f" % tot, "calls %d/%d" % (ok, att), "rows with unknown cost", unknown, "errors", errs)
for k, v in sorted(by.items()): print(k, "$%.6f" % v[0], "%d/%d" % (v[1], v[2]))
print("inbound_error rows", c.execute("select count(*) from tool_log where tool='inbound_error'").fetchone()[0])
print("cases", c.execute("select count(*) from cases").fetchone()[0], "contacts", c.execute("select count(*) from channel_contacts").fetchone()[0],
      "farmer_text_proposal cases", c.execute("select count(distinct case_id) from tool_log where tool='farmer_text_proposal'").fetchone()[0],
      "queue_case", c.execute("select count(*) from tool_log where tool='queue_case'").fetchone()[0])
print("status", c.execute("select status,count(*) from cases group by status").fetchall())
