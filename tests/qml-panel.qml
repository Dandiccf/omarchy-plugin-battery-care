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
  Care.BatteryPanel { id: panel; bar: mockBar; helper: Qt.resolvedUrl("Care/tests/fake_backend.py").toString().replace("file://", "") }
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
          panel.receive('{"error":"status failed"}', false)
          check(!panel.statusValid && panel.enabledControls.length === 0, "stale controls must disable")
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
