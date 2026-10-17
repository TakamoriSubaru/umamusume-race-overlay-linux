/* tools/hook_race.js - Umamusume Race Memory Hook */
console.log("[*] Loading Umamusume memory hook script...");

function initHook() {
    var gameAssembly = Module.findBaseAddress("GameAssembly.dll");
    if (!gameAssembly) {
        setTimeout(initHook, 1000);
        return;
    }

    console.log("[+] Found GameAssembly.dll at: " + gameAssembly);

    if (typeof Il2Cpp !== "undefined") {
        Il2Cpp.perform(function () {
            try {
                var assembly = Il2Cpp.domain.assembly("Assembly-CSharp");
                if (!assembly) {
                    setTimeout(initHook, 2000);
                    return;
                }

                var image = assembly.image;
                var raceSimClass = image.class("Gallop.RaceSimulateManager");
                
                if (raceSimClass) {
                    var updateMethod = raceSimClass.method("Update");
                    if (updateMethod) {
                        updateMethod.implementation = function () {
                            try {
                                var isSimulating = this.field("isSimulating").value;
                                var raceTime = this.field("raceTime").value;

                                send({
                                    event: 'clock_tick',
                                    data: {
                                        active: Boolean(isSimulating),
                                        time: Number(raceTime) || 0.0
                                    }
                                });
                            } catch (e) {
                                // Ignore field read exceptions during scene changes
                            }
                            return this.Update();
                        };
                        console.log("[+] Successfully hooked RaceSimulateManager.Update!");
                    }
                }

                send({ event: 'status', message: 'Frida hooks active: waiting for simulation...' });

            } catch (ex) {
                console.log("[-] IL2CPP Hook error: " + ex);
            }
        });
    }
}

setImmediate(initHook);