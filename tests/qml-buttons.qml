import QtQuick
import Quickshell
import "Care" as Care
ShellRoot {
  QtObject { id: nav; property bool cursorActive: true; property int cursorIndex: 0 }
  Care.CareButton { id: protect; navigationOwner: nav; navigationIndex: 0; active: true }
  Care.CareButton { id: full; navigationOwner: nav; navigationIndex: 1 }
  Timer {
    interval: 200; running: true
    onTriggered: {
      function check(value, text) { if (!value) throw new Error(text) }
      try {
        check(protect.hasCursor, "keyboard cursor missing")
        protect.hovered(true)
        protect.hovered(false)
        check(!protect.hasCursor && !protect.hot, "protection hover stuck")
        check(protect.active, "selected state should remain distinct from hover")
        nav.cursorActive = true; nav.cursorIndex = 1
        check(full.hasCursor, "full charge keyboard cursor missing")
        full.hovered(true); full.hovered(false)
        check(!full.hasCursor && !full.hot, "full charge hover stuck")
        console.log("PASS: production CareButton keyboard/hover bindings")
      } catch (error) { console.log("FAIL: " + error) }
      Qt.quit()
    }
  }
}
