import frida
import time
import sys

def on_message(message, data):
    print(f"[Message] {message}")

def main():
    print("Connecting to Frida server inside Proton (127.0.0.1:27042)...")
    manager = frida.get_device_manager()
    device = manager.add_remote_device("127.0.0.1:27042")

    print("Enumerating processes inside Proton environment...")
    processes = device.enumerate_processes()
    for p in processes:
        if "umamusume" in p.name.lower():
            print(f"Found game process! PID: {p.pid}, Name: {p.name}")
            session = device.attach(p.pid)
            
            script_code = """
            console.log("[Frida] Successfully attached inside Wine/Proton!");
            var gameModule = Process.findModuleByName("GameAssembly.dll");
            if (gameModule) {
                console.log("[Frida] GameAssembly.dll loaded at: " + gameModule.base);
            }
            """
            script = session.create_script(script_code)
            script.on("message", on_message)
            script.load()
            
            print("Attached! Press Ctrl+C to exit.")
            sys.stdin.read()
            return

    print("Umamusume process not found inside Proton server. Make sure the game is running!")

if __name__ == "__main__":
    main()
