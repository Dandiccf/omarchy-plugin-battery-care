import QtQuick
import Quickshell
import "Care" as Care

ShellRoot {
  id: testRoot
  property int editSignals: 0
  QtObject {
    id: controller
    property var snapshot: null
    property bool busy: false
    property bool saving: false
    property string error: ""
    property int saves: 0
    signal saved()
    function refresh() {}
    function apply(preferences, revision) {
      if (revision !== "initial") throw new Error("wrong draft revision")
      saves++
      var next = JSON.parse(JSON.stringify(snapshot))
      next.preferences = JSON.parse(JSON.stringify(preferences))
      next.active = preferences[preferences.separate ? next.source : "shared"]
      snapshot = next
      saved()
    }
  }
  Care.ScreenSettings { id: editor; width: 408; controller: controller }
  Care.TimeoutEditor { id: timeout; width: 170; onEditingStarted: testRoot.editSignals++ }
  Timer {
    interval: 100; running: true
    onTriggered: {
      function check(value, text) { if (!value) throw new Error(text) }
      try {
        controller.snapshot = {
          preferences: {version: 1, separate: false, shared: {screensaver: 150, lock: 300}, battery: {screensaver: 150, lock: 300}, ac: {screensaver: 150, lock: 300}},
          source: "battery", revision: "initial", active: {screensaver: 150, lock: 300}, pending: false, stayAwake: false
        }
        editor.toggle()
        check(editor.expanded && !editor.dirty, "opening must not change saved settings")
        editor.toggleSeparate()
        editor.edit("ac", "lock", 900)
        editor.cancel()
        check(controller.saves === 0 && !editor.expanded, "cancel must not save")
        check(editor.draft.ac.lock === 300, "cancel restores saved draft")
        editor.toggle()
        editor.toggleSeparate()
        editor.edit("ac", "screensaver", 600)
        editor.edit("ac", "lock", 900)
        var update = JSON.parse(JSON.stringify(controller.snapshot)); update.stayAwake = true
        controller.snapshot = update
        check(editor.draft.ac.lock === 900 && editor.dirty, "poll must preserve unsaved edits")
        editor.apply()
        check(controller.saves === 1 && !editor.dirty, "apply saves exactly once")
        check(controller.snapshot.preferences.ac.lock === 900, "AC timeout saved")
        check(controller.snapshot.preferences.battery.lock === 300, "battery timeout retained")
        update = JSON.parse(JSON.stringify(controller.snapshot)); update.source = "ac"
        controller.snapshot = update
        editor.toggleSeparate()
        check(editor.draft.shared.lock === 900, "shared mode inherits currently selected source")
        editor.apply()
        check(!controller.snapshot.preferences.separate && controller.snapshot.active.lock === 900, "shared settings applied")
        timeout.selector.changed("300")
        check(timeout.seconds === 300 && timeout.valid, "preset selection")
        timeout.custom = true
        check(!timeout.valid, "empty custom fields must not be accepted")
        timeout.selector.changed("custom")
        check(testRoot.editSignals === 2 && timeout.valid, "custom editing must mark the draft before typing")
        timeout.reset(91)
        check(timeout.seconds === 91 && timeout.valid && !timeout.custom, "custom value survives refresh")
        editor.width = 250
        check(editor.valid, "narrow form remains valid")
        console.log("PASS: Screen & lock draft, Apply/Cancel, power-source selection, and timeout editor")
      } catch (error) { console.log("FAIL: " + error) }
      Qt.quit()
    }
  }
}
