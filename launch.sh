cat << 'EOF' > /home/darryl/.local/share/Steam/steamapps/common/UmamusumePrettyDerby/launch.sh
#!/bin/bash
GAME_DIR="/home/darryl/.local/share/Steam/steamapps/common/UmamusumePrettyDerby"

# Start frida-server.exe inside Steam's Proton environment context in the background
"$GAME_DIR/frida-server.exe" --listen=0.0.0.0:27042 &

# Execute the game command passed by Steam (%command%)
exec "$@"
EOF
chmod +x /home/darryl/.local/share/Steam/steamapps/common/UmamusumePrettyDerby/launch.sh