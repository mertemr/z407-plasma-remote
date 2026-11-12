#!/usr/bin/env bash
# Removes everything install.sh set up. Tracked levels in ~/.local/state/z407 are kept.
set -euo pipefail

applet_id="com.github.mertemr.z407"

systemctl --user disable --now z407d.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/z407d.service" "$HOME/.local/bin/z407ctl"
systemctl --user daemon-reload
kpackagetool6 -t Plasma/Applet -r "$applet_id" 2>/dev/null || true

echo "Removed. Delete ~/.local/state/z407 to also drop the tracked levels."
