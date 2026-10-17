"""Frida memory hook thread for native Linux Umamusume overlay timing."""

import os
import time
import frida
from PyQt6.QtCore import QThread, pyqtSignal


class MemoryHookThread(QThread):
    race = pyqtSignal(dict, dict)  # Emits (payload, result_map)
    clock = pyqtSignal(dict)       # Emits live clock ticks
    status = pyqtSignal(str)       # Tray/UI status messages
    quit_request = pyqtSignal()

    def __init__(self, game_match="umamusume"):
        super().__init__()
        self.game_match = game_match
        self.offset = 0.0
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

                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.join(base_dir, "tools", "hook_race.js")

                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        script_code = f.read()
                else:
                    script_code = 'console.log("[Frida] hook_race.js not found!");'

                script = session.create_script(script_code)
                script.on('message', lambda msg, data: self._handle_message(msg))
                script.load()

                self.status.emit("Memory hooks active - monitoring race...")

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
                    # Expecting payload data and result map from JS hook
                    data = payload.get('data', {})
                    self.race.emit(data.get('payload', {}), data.get('rmap', {}))
                elif event_type == 'clock_tick':
                    self.clock.emit({
                        "type": "clock",
                        "active": payload.get('data', {}).get('active', False),
                        "time": payload.get('data', {}).get('time', 0.0),
                        "aiStates": {}
                    })
                elif event_type == 'status':
                    self.status.emit(payload.get('message', ''))