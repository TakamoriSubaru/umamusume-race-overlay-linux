import frida
import os
import time
from PyQt6.QtCore import QThread, pyqtSignal

class MemoryHookThread(QThread):
    race = pyqtSignal(dict)       # Emits parsed race payload/runners
    clock = pyqtSignal(dict)      # Emits live race clock updates
    status = pyqtSignal(str)      # Status messages for tray/UI
    quit_request = pyqtSignal()   # Quit signal if needed

    def __init__(self, game_match="umamusume"):
        super().__init__()
        self.game_match = game_match
        self.offset = 0.0
        self.delay = 0.0
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        self.status.emit("Waiting for Umamusume process...")
        session = None

        while not self._stop:
            try:
                target_pid = None
                for p in frida.enumerate_processes():
                    if self.game_match.lower() in p.name.lower():
                        target_pid = p.pid
                        break

                if not target_pid:
                    time.sleep(1.5)
                    continue

                self.status.emit(f"Attached to Process PID: {target_pid}")
                session = frida.attach(target_pid)

                script_path = os.path.join(os.path.dirname(__file__), "..", "tools", "hook_race.js")
                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        script_code = f.read()
                else:
                    script_code = 'console.log("[Frida] Default attached fallback.");'

                script = session.create_script(script_code)
                script.on('message', lambda msg, data: self._handle_message(msg))
                script.load()

                self.status.emit("Memory hooks active - waiting for race...")

                while not self._stop:
                    time.sleep(0.5)

            except frida.ProcessNotFoundError:
                self.status.emit("Game closed. Waiting for launch...")
                time.sleep(2.0)
            except Exception as e:
                self.status.emit(f"Hook error: {e}")
                time.sleep(2.0)

            if session:
                try:
                    session.detach()
                except Exception:
                    pass

    def _handle_message(self, message):
        if message.get('type') == 'send':
            payload = message.payload
            if isinstance(payload, dict):
                event_type = payload.get('event')
                if event_type == 'race_data':
                    # Emits full race setup and runners list
                    self.race.emit(payload.get('data', {}))
                elif event_type == 'clock_tick':
                    # Emits live clock updates and active state
                    self.clock.emit(payload.get('data', {}))
                elif event_type == 'status':
                    self.status.emit(payload.get('message', ''))