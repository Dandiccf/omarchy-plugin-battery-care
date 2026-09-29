#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_id=dandiccf.battery-care
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/$plugin_id"
created_link=0
complete=0
cleanup() {
  if (( created_link && ! complete )) && [[ -L "$plugin_dir" ]] && [[ $(readlink -f "$plugin_dir") == "$source_dir" ]]; then
    rm -- "$plugin_dir"
  fi
}
trap cleanup EXIT
omarchy plugin validate "$source_dir"
/usr/bin/python3 -c 'from gi.repository import Gio, GLib'
if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
  [[ $(readlink -f "$plugin_dir") == "$source_dir" ]] || { echo "Plugin destination already exists: $plugin_dir" >&2; exit 1; }
else
  mkdir -p "$(dirname "$plugin_dir")"
  ln -s "$source_dir" "$plugin_dir"
  created_link=1
fi
config="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/shell.json"
if [[ -f "$config" ]]; then cp -p "$config" "$config.battery-care.$(date +%Y%m%d%H%M%S).bak"; fi
omarchy-shell shell rescanPlugins
for ((attempt=0; attempt<40; attempt++)); do
  if omarchy plugin list --json | jq -e --arg id "$plugin_id" 'any(.[]; .id == $id)' >/dev/null; then break; fi
  sleep 0.1
done
omarchy plugin enable "$plugin_id"
complete=1
echo "Battery Care enabled from $source_dir. Choose the protection button to enable its charge preset."
