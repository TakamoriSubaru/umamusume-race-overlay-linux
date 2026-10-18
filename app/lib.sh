# Small helpers for the start scripts. Used with:  source ./lib.sh

# say "Title" "Message"
# Prints the message. When the program was not started from a terminal (desktop icon, Steam),
# it also shows it in a small popup window, so you never have to open a command prompt.
say() {
  echo -e "$1: $2"
  [ -t 1 ] && return 0
  if command -v zenity >/dev/null 2>&1; then
    zenity --info --no-wrap --title="$1" --text="$2" >/dev/null 2>&1 &
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$1" --msgbox "$2" >/dev/null 2>&1 &
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send "$1" "$2" >/dev/null 2>&1
  fi
}
