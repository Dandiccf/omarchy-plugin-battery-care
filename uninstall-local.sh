#!/usr/bin/env bash
# Reverse install-local.sh; refuses to remove an unrelated or git-managed plugin.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
plugin_dir="$config_home/omarchy/plugins/dandiccf.battery-care"
if [[ ! -L "$plugin_dir" || $(readlink -f "$plugin_dir") != "$source_dir" ]]; then
  echo "This is not the local development link. Run battery.py release, then remove the plugin through Omarchy." >&2
  exit 1
fi
# Refuses to abandon absent batteries with pending temporary sessions.
/usr/bin/python3 "$source_dir/battery.py" release >/dev/null
omarchy plugin disable dandiccf.battery-care
omarchy plugin enable omarchy.power
rm -- "$plugin_dir"
rm -f -- "$config_home/systemd/user/omarchy-battery-care.timer" "$config_home/systemd/user/omarchy-battery-care.service"
systemctl --user daemon-reload
omarchy-shell shell rescanPlugins
echo "Restored the standard Power widget and removed the recovery units. Source files remain in $source_dir."
