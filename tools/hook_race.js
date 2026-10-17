/* tools/hook_race.js - Umamusume Race Simulation Memory Hook via Frida */
console.log("[*] Loading Umamusume race simulation memory hook...");

function hookGame() {
    var gameAssembly = Module.findBaseAddress("GameAssembly.dll");
    if (!gameAssembly) {
        console.log("[*] Waiting for GameAssembly.dll...");
        setTimeout(hookGame, 1000);
        return;
    }

    console.log("[+] Found GameAssembly.dll at: " + gameAssembly);

    if (typeof Il2Cpp !== "undefined") {
        Il2Cpp.perform(function () {
            try {
                console.log("[+] IL2CPP attached successfully.");
                var assembly = Il2Cpp.domain.assembly("Assembly-CSharp");
                if (!assembly) {
                    console.log("[-] Assembly-CSharp not found yet. Retrying...");
                    setTimeout(hookGame, 2000);
                    return;
                }

                var image = assembly.image;
                var raceManagerClass = image.class("Gallop.RaceSimulateManager");
                if (raceManagerClass) {
                    console.log("[+] Found Gallop.RaceSimulateManager!");
                    
                    var updateMethod = raceManagerClass.method("Update");
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
                            } catch (err) {
                                // Silent fail during scene transitions
                            }
                            return this.Update();
                        };
                        console.log("[+] Hooked RaceSimulateManager.Update successfully!");
                    }
                } else {
                    console.log("[-] Gallop.RaceSimulateManager class not found in image.");
                }

                send({ event: "status", message: "Frida memory hooks active and monitoring race state." });

            } catch (e) {
                console.log("[-] Error during IL2CPP perform: " + e);
            }
        });
    } else {
        console.log("[-] Frida Il2Cpp module wrapper not detected.");
    }
}

setImmediate(hookGame);