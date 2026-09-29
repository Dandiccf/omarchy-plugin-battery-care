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
for test in buttons panel; do
  BATTERY_CARE_TEST_STATE="$fixture_dir/state" QT_QPA_PLATFORM=wayland timeout 15 qs -p "$fixture_dir/$test.qml" --no-color >"$fixture_dir/$test.log" 2>&1 || {
    cat "$fixture_dir/$test.log"; exit 1;
  }
  if rg -q 'FAIL:|TypeError|ReferenceError|Failed to load configuration' "$fixture_dir/$test.log" || ! rg -q 'PASS:' "$fixture_dir/$test.log"; then
    cat "$fixture_dir/$test.log"; exit 1
  fi
  rg 'PASS:' "$fixture_dir/$test.log"
done
