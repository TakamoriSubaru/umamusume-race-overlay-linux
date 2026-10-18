import frida, subprocess, time, json, sys, collections
JS = open("/home/claude/umamusume-race-overlay-linux/tools/hook_race.js").read()
host = subprocess.Popen(["/tmp/fr/host"])
time.sleep(0.2)
sess = frida.attach(host.pid)
msgs = []; T0 = time.time()
def on_msg(m, data):
    if m["type"] == "send": msgs.append((time.time()-T0, m["payload"]))
    else: msgs.append((time.time()-T0, {"type":"FRIDA-ERROR", "text": m.get("description"), "stack": m.get("stack")}))
sc = sess.create_script(JS); sc.on("message", on_msg); sc.load()
ex = sc.exports_sync

# wait for il2cpp ready (module loads at 1.5s, runtime inits at 2.4s in the host)
for _ in range(60):
    st = ex.status()
    if st["ready"]: break
    time.sleep(0.2)
print("READY after %.1fs ->" % (time.time()-T0), json.dumps(st))

print("\n--- discover('Race', 'Scenario|Update|Set', fields)")
for e in ex.discover("Race|Horse|Frame", "Scenario|Update|Set|Refresh", True):
    print(" ", e["cls"]); [print("     m", m) for m in e["methods"]]; [print("     f", f) for f in e["fields"][:4]]

print("\n--- configure scenario hook (string)")
r = ex.configure({"scenario": {"classes": ["Gallop.RaceScenarioLoader"], "method": "SetScenario", "argc": 2, "arg": 0, "kind": "string"}})
print(json.dumps(r["resolved"]), r["missing"])
open("/tmp/fr/go", "w").close(); GO = time.time()-T0

time.sleep(8.3 - (time.time()-T0-GO))
print("\n--- configure bytes hook + struct-array horses (between race 2 and 3)")
r = ex.configure({"scenario": {"classes": ["Gallop.RaceScenarioLoader"], "method": "SetBytes", "argc": 1, "arg": 0, "kind": "bytes"},
                  "tick": {"horses": ["_frameHorses"]}})
print(json.dumps(r["resolved"]), r["missing"])
time.sleep(1.6)
print("\n--- trace('Gallop', 2s) during race 3")
tr = ex.trace("Gallop", 2)
print(" hooked", tr["hooked"], "called", tr["called"])
for row in tr["top"][:5]: print("  ", row)
print("  bigArguments:", [ (r["sig"], r["maxStr"], r["maxBytes"]) for r in tr["bigArguments"] ])
host.wait(timeout=30)
time.sleep(0.5)

print("\n================ MESSAGE SUMMARY")
c = collections.Counter(p["type"] for _, p in msgs); print(dict(c))
for ts, p in msgs:
    if p["type"] == "status": print("%6.2f status/%s: %s %s" % (ts, p["level"], p["text"][:150], ("missing="+str(p["missing"])) if p.get("missing") else ""))
    if p["type"] == "FRIDA-ERROR": print("%6.2f !!!! ERROR" % ts, p)
races = [(ts,p) for ts,p in msgs if p["type"]=="race"]
for ts,p in races:
    print("%6.2f RACE replay=%d chars gz=%s runners=%s rmap=%s shape=%s" % (ts, len(p["replay"]), p["compressed"],
          [(r["frameOrder"], r["name"], r["trainer"], r["charaId"]) for r in p["runners"]], list(p["rmap"].items())[:1], p["courseShape"]))
clocks = [(ts,p) for ts,p in msgs if p["type"]=="clock"]
print("\nclock messages:", len(clocks))
seq = [(round(ts,2), p["active"], round(p["time"],2)) for ts,p in clocks]
act = [s for s in seq if s[1]]
print("first 3:", seq[:3]); print("every 10th:", [s[2] for s in act[::10]])
print("active:false at:", [s for s in seq if not s[1]])
hs = [(ts,p) for ts,p in msgs if p["type"]=="horses"]
print("\nhorses msgs:", len(hs)); print(" first (object array):", json.dumps(hs[0][1])[:330])
print(" last  (struct array):", json.dumps(hs[-1][1])[:330])
