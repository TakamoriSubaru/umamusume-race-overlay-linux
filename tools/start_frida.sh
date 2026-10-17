#!/bin/bash

# Python socket check for port 27042
is_port_open() {
    python3 -c "import socket, sys; s = socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1', 27042)) == 0 else 1)"
}

if is_port_open; then
    echo "[!] frida-server is ALREADY running on port 27042."
else
    echo "[*] Launching frida-server inside game container..."
    /home/darryl/.local/share/Steam/ubuntu12_32/steam-runtime/amd64/usr/bin/steam-runtime-launch-client \
      --bus-name=com.steampowered.App3224770 \
      -- wine "/home/darryl/.local/share/Steam/steamapps/common/UmamusumePrettyDerby/frida-server.exe" --listen=0.0.0.0:27042 > /dev/null 2>&1 &

    sleep 2

    if is_port_open; then
        echo "[+] Success! frida-server is live on port 27042."
    else
        echo "[-] Failed to connect. Make sure Umamusume is running!"
    fi
fi