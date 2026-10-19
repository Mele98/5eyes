import sys, time
sys.path.insert(0, __file__.rsplit("\\",1)[0].rsplit("/",1)[0])
from exp_common import *
names = sys.argv[1].split(",")
scales = [float(s) for s in sys.argv[2].split(",")]
for n in names:
    for s in scales:
        t=time.time(); r = run(n, s)
        g = r["result"].goal_achievability
        pr = [round(float(x.get("probability") or x.get("probability_pct") or 0),3) for x in g if x.get("evaluation_scope")!="joint_plan"] if g else None
        print(n, s, r["decision"], r["sig"].get("reason"), "p=",r["p"], "imp=%.3g"%(r["improvement"] or 0), "cand=",r["candidate"], "anch_eq=",eq(r["anchor"]), "final_eq=",eq(r["final"]), "ms=",r["elapsed_ms"], "wall=%.1f"%(time.time()-t), flush=True)
