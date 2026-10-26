import QtQuick
import Quickshell
import "Care" as Care
ShellRoot {
  Item {
    id: mockBar
    property color foreground: "white"
    property color urgent: "red"
    property bool foregroundAnimationEnabled: false
    property color barForeground: "white"
    property color popupForeground: "white"
    property color popupBackground: "black"
    property bool tooltipsEnabled: false
    function hideTooltip() {}
    function showTooltip() {}
    property color background: "black"
    property string fontFamily: "monospace"
    property string position: "top"
    property int barSize: 30
    property var shell: null
    property bool vertical: false
    property int iconSize: 18
  }
  Care.BatteryPanel { id: panel; bar: mockBar; idleAutomationEnabled: false; helper: Qt.resolvedUrl("Care/tests/fake_backend.py").toString().replace("file://", ""); energyHelper: Qt.resolvedUrl("Care/tests/fake_energy.py").toString().replace("file://", "") }
  Timer {
    property int phase: 0
    property int count: 0
    interval: 100; running: true; repeat: true
    onTriggered: {
      function check(value, text) { if (!value) throw new Error(text) }
      try {
        if (++count > 80) throw new Error("panel test timed out")
        if (!panel.statusValid || panel.busy) return
        if (phase === 0) {
          check(panel.battery.enabled, "initial protection")
          var button = panel.children.find(function(child) { return child.percentageLabel !== undefined })
          check(button && button.percentageLabel.endsWith("%"), "percentage label available")
          if (button.separateLabel) {
            check(button.labelText === button.percentageLabel, "modern bar has separate percentage label")
            check(button.text.indexOf("%") < 0, "modern optical glyph only contains battery icon")
          } else check(button.text.indexOf("%") >= 0, "legacy bar combines percentage and icon")
          mockBar.vertical = true
          check(button.percentageLabel === "" && button.text.indexOf("%") < 0, "vertical bar hides percentage")
          mockBar.vertical = false
          panel.charge("off"); phase++
        } else if (phase === 1) {
          check(panel.battery.mode === "off" && !panel.battery.enabled, "Off command routing")
          panel.charge("full"); phase++
        } else if (phase === 2) {
          check(panel.battery.mode === "full" && !panel.battery.enabled, "Full command routing")
          panel.batteryPower = true
          panel.cursorIndex = 1; panel.activateCursor(); phase++
        } else {
          check(panel.battery.enabled && panel.battery.mode === "protect", "Cancel command routing")
          check(panel.energyHistory.samples.length >= 1 && panel.energyError === "", "energy sampler runs")
          var unit = function(name, kind, cpu) { return {id: name, name: name, kind: kind, cpu: cpu, gpuNs: 0, gpuCycles: 0} }
          panel.receiveEnergy(JSON.stringify({time: 1, gpuClock: null, units: [unit("Busy", "app", 0), unit("Daemon", "service", 0), unit("Quiet", "app", 0)]}))
          check(!panel.energy.ready, "one energy sample is not a measurement")
          panel.receiveEnergy(JSON.stringify({time: 11, gpuClock: null, units: [unit("Busy", "app", 8e6), unit("Daemon", "service", 1e6), unit("Quiet", "app", 1e4)]}))
          check(panel.energy.ready && panel.energy.items.length === 2, "significant energy users listed")
          check(panel.energy.items[0].name === "Busy" && Math.round(panel.energy.items[0].impact) === 80, "energy impact ordering")
          check(panel.energy.items[0].watts === null, "no watt estimate without a battery baseline")
          panel.receiveEnergy('{"error":"no cgroups"}')
          check(panel.energyError.indexOf("no cgroups") >= 0 && panel.energy.ready, "energy errors keep the last reading")
          check(panel.enabledControls.indexOf(panel.historyIndex) >= 0, "history reachable by keyboard")
          panel.receiveHistory('{"buckets":[{"start":0,"seconds":900,"battery":900,"charged":0,"wh":2,"active":10,"level":40,"apps":[{"name":"Busy","kind":"app","cores":10}]}]}')
          check(panel.historyBuckets.length === 1 && panel.historyError === "", "history loads")
          panel.receiveHistory('{"error":"unsafe file"}')
          check(panel.historyError === "unsafe file" && panel.historyBuckets.length === 1, "history errors keep the last data")
          panel.receive('{"error":"status failed"}', false)
          check(!panel.statusValid && panel.enabledControls.length === 1 && panel.enabledControls[0] === panel.historyIndex, "stale controls must disable; history stays available")
          panel.receive('{"error":"action failed"}', true)
          panel.receive('{"batteries":[],"onBattery":true}', false)
          check(panel.actionError === "action failed", "poll must not erase action error")
          panel.receive('broken json', false)
          check(!panel.statusValid, "invalid json must disable controls")
          panel.receive('{"batteries":[{"key":"one","supported":false},{"key":"two","supported":false}],"onBattery":true}', false)
          panel.selectBattery(1)
          check(panel.battery.key === "two", "keyboard battery selection")
          panel.receive('{"batteries":[],"onBattery":true,"stateError":"corrupt state"}', false)
          check(!panel.statusValid && panel.stateError === "corrupt state", "corrupt state must disable actions")
          console.log("PASS: production BatteryPanel action routing and error handling")
          Qt.quit()
        }
      } catch (error) { console.log("FAIL: " + error); Qt.quit() }
    }
  }
}
