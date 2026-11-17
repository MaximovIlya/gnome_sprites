#!/bin/bash
# Install the desktop pets as GNOME Shell extensions for the current user.
# Usage: ./install.sh            -> install all
#        ./install.sh airship    -> only the airship
#        ./install.sh fox        -> only the fox
#        ./install.sh cat        -> only the cat
#        ./install.sh dogfight   -> only the dogfight
set -euo pipefail

cd "$(dirname "$0")"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions"
mkdir -p "$DEST"

case "${1:-all}" in
    fox) EXTS=(fox-pet@local) ;;
    airship) EXTS=(airship-pet@local) ;;
    cat) EXTS=(cat-pet@local) ;;
    dogfight) EXTS=(dogfight@local) ;;
    all) EXTS=(fox-pet@local airship-pet@local cat-pet@local dogfight@local) ;;
    *) echo "usage: $0 [fox|cat|airship|dogfight|all]" >&2; exit 1 ;;
esac

for uuid in "${EXTS[@]}"; do
    rm -rf "${DEST:?}/$uuid"
    cp -r "$uuid" "$DEST/"
    echo "installed $uuid -> $DEST/$uuid"
    # Add to enabled-extensions so it starts after the next login.
    current=$(gsettings get org.gnome.shell enabled-extensions)
    if [[ "$current" != *"'$uuid'"* ]]; then
        if [[ "$current" == "@as []" || "$current" == "[]" ]]; then
            gsettings set org.gnome.shell enabled-extensions "['$uuid']"
        else
            gsettings set org.gnome.shell enabled-extensions "${current%]}, '$uuid']"
        fi
    fi
    gnome-extensions enable "$uuid" 2>/dev/null || true
done

echo
echo "Done. On Wayland log out and back in to load the extensions"
echo "(on X11: Alt+F2, type r, Enter)."
