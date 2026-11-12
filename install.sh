#!/usr/bin/env bash
# Installs the z407d user service, the z407ctl client and the Plasma system tray widget.
# Usage: ./install.sh [BLE_ADDRESS]
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
address="${1:-}"
applet_id="com.github.mertemr.z407"
unit_dir="$HOME/.config/systemd/user"

for tool in uv systemctl kpackagetool6; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

uv sync --project "$repo" --no-dev

install -d "$HOME/.local/bin" "$unit_dir"
chmod +x "$repo/z407_remote/ctl.py"
ln -sf "$repo/z407_remote/ctl.py" "$HOME/.local/bin/z407ctl"

cat > "$unit_dir/z407d.service" <<UNIT
[Unit]
Description=Logitech Z407 BLE remote service
After=bluetooth.target

[Service]
Environment=Z407_ADDRESS=$address
ExecStart=$repo/.venv/bin/z407d
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable z407d.service
systemctl --user restart z407d.service

if kpackagetool6 -t Plasma/Applet -s "$applet_id" >/dev/null 2>&1; then
    kpackagetool6 -t Plasma/Applet -u "$repo/plasmoid"
else
    kpackagetool6 -t Plasma/Applet -i "$repo/plasmoid"
fi

# Updating the package removes it from the tray, so add it back as an always-shown entry.
tray_script="
var id = '$applet_id';
panels().forEach(function (panel) {
    panel.widgets('org.kde.plasma.systemtray').forEach(function (tray) {
        tray.currentConfigGroup = ['General'];
        ['extraItems', 'shownItems'].forEach(function (key) {
            var items = tray.readConfig(key);
            if (typeof items === 'string') items = items ? items.split(',') : [];
            if (items.indexOf(id) < 0) { items.push(id); tray.writeConfig(key, items); }
        });
        tray.reloadConfig();
    });
});"
qdbus=$(command -v qdbus6 || command -v qdbus || true)
if [ -n "$qdbus" ] && "$qdbus" org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$tray_script" >/dev/null 2>&1; then
    echo "Done. Z407 Remote is in the system tray."
else
    echo "Done. Enable Z407 Remote under System Tray Settings → Entries."
fi
