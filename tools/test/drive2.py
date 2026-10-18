import frida, subprocess, time, json, collections
JS = open("/home/claude/umamusume-race-overlay-linux/tools/hook_race.js").read()
import os; os.path.exists("/tmp/fr/go2") and os.remove("/tmp/fr/go2")
host = subprocess.Popen(["/tmp/fr/host2"]); time.sleep(0.2)
sess = frida.attach(host.pid); msgs=[]
sc = sess.create_script(JS); sc.on("message", lambda m,d: msgs.append(m["payload"] if m["type"]=="send" else {"type":"FRIDA-ERROR","d":m}))
sc.load(); ex = sc.exports_sync
for _ in range(40):
    if ex.status()["ready"]: break
    time.sleep(0.2)
r = ex.configure({"tick":{"horses":["_horseList"]}}); print("resolved:", json.dumps(r["resolved"]), "missing:", r["missing"])
open("/tmp/fr/go2","w").close()
rc = host.wait(timeout=30); time.sleep(0.4)
print("host exit code:", rc, "(0 = survived, <0 = crashed by signal)")
c = collections.Counter(p["type"] for p in msgs); print(dict(c))
for p in msgs:
    if p["type"]=="status" and p["level"] in ("warn","error"): print("  ", p["level"], p["text"][:170])
    if p["type"]=="FRIDA-ERROR": print("  !!!", p)
    if p["type"]=="status" and "race" in p["text"] and p["level"]=="info": print("  ", p["text"])
ck=[p for p in msgs if p["type"]=="clock"]
print("clock actives/inactive:", sum(1 for p in ck if p["active"]), sum(1 for p in ck if not p["active"]))
print("max clock time sent:", max(p["time"] for p in ck), "(1e9 / NaN must never be sent)")
hs=[p for p in msgs if p["type"]=="horses"]; print("horses via List<T>:", len(hs), json.dumps(hs[0]["horses"][0]) if hs else None)
