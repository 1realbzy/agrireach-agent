import sqlite3, re
c = sqlite3.connect('/tmp/apprun6/main/t.db')
per = {}
for cid, s in c.execute("select case_id,result_summary from tool_log where tool='model_usage'"):
    m = re.match(r'(\d+) of (\d+) model calls succeeded, cost \$([0-9.e-]+)', s)
    per[cid] = (int(m[1]), int(m[2]), float(m[3]))
print(per)
def agg(ids):
    g = [per[i] for i in ids]; return round(sum(x[2] for x in g), 6), sum(x[0] for x in g), sum(x[1] for x in g)
print('graded 1-9', agg(range(1, 10)))
print('conc F9 10-19', agg(range(10, 20)))
print('conc F1 20-23', agg(range(20, 24)))
print('all', agg(per))
