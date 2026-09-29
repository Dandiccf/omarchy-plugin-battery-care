#!/usr/bin/env bash
# Requires a Wayland session for PanelWindow, but uses only a simulated battery.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
fixture_dir=$(mktemp -d /tmp/battery-care-qml.XXXXXX)
trap 'rm -rf -- "$fixture_dir"' EXIT
ln -s "$root" "$fixture_dir/Care"
ln -s /usr/share/omarchy/shell/Commons "$fixture_dir/Commons"
ln -s /usr/share/omarchy/shell/Ui "$fixture_dir/Ui"
cp "$root/tests/qml-buttons.qml" "$fixture_dir/buttons.qml"
cp "$root/tests/qml-panel.qml" "$fixture_dir/panel.qml"
cp "$root/tests/qml-screen.qml" "$fixture_dir/screen.qml"
cp "$root/tests/qml-idle-controller.qml" "$fixture_dir/idle-controller.qml"
cp "$root/tests/qml-timeout-menu.qml" "$fixture_dir/timeout-menu.qml"
mkdir -p "$fixture_dir/config/omarchy"
printf '%s\n' '{"version":1,"idle":{"screensaver":150,"lock":300}}' > "$fixture_dir/config/omarchy/shell.json"
for test in buttons panel screen idle-controller timeout-menu; do
  XDG_CONFIG_HOME="$fixture_dir/config" XDG_STATE_HOME="$fixture_dir/statehome" BATTERY_CARE_IDLE_TEST_STATE="$fixture_dir/idle-runtime.json" BATTERY_CARE_TEST_STATE="$fixture_dir/state" QT_QPA_PLATFORM=wayland timeout 15 qs -p "$fixture_dir/$test.qml" --no-color >"$fixture_dir/$test.log" 2>&1 || {
    cat "$fixture_dir/$test.log"; exit 1;
  }
  if rg -q 'FAIL:|TypeError|ReferenceError|Failed to load configuration' "$fixture_dir/$test.log" || ! rg -q 'PASS:' "$fixture_dir/$test.log"; then
    cat "$fixture_dir/$test.log"; exit 1
  fi
  rg 'PASS:' "$fixture_dir/$test.log"
done
