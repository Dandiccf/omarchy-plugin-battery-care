import QtQuick
import Quickshell
import Quickshell.Io
import "Care" as Care

ShellRoot {
  Care.IdleController {
    id: controller
    activityAllowed: true
    helper: Qt.resolvedUrl("Care/tests/fake_idle_backend.py").toString().replace("file://", "")
  }
  Process { id: fixture }
  Timer {
    property int phase: 0
    property int count: 0
    interval: 100; running: true; repeat: true
    onTriggered: {
      function check(value, text) { if (!value) throw new Error(text) }
      try {
        if (++count > 100) throw new Error("idle controller test timed out: " + controller.error)
        if (!controller.snapshot || controller.busy || fixture.running) return
        if (phase < 7 && (controller.error || controller.statusError)) throw new Error(controller.error || controller.statusError)
        if (phase === 0) {
          check(!controller.snapshot.managed, "initial config must remain unmanaged")
          var prefs = JSON.parse(JSON.stringify(controller.snapshot.preferences))
          prefs.separate = true
          prefs.battery = {screensaver: 125, lock: 305}
          prefs.ac = {screensaver: 625, lock: 905}
          controller.apply(prefs, controller.snapshot.revision)
          phase++
        } else if (phase === 1) {
          check(controller.snapshot.active.lock === 305 && controller.snapshot.managed, "real backend Apply")
          controller.activityAllowed = false
          fixture.command = ["/usr/bin/python3", controller.helper, "test-ac-idle"]
          fixture.running = true
          phase++
        } else if (phase === 2) {
          controller.refresh(); phase++
        } else if (phase === 3) {
          check(controller.snapshot.source === "ac" && controller.snapshot.pending, "charger switch queued")
          check(controller.snapshot.active.lock === 305, "existing lock deadline must remain")
          // Even an optimistic activity signal may not override Omarchy's active cycle.
          controller.activityAllowed = true
          controller.refresh(); phase++
        } else if (phase === 4) {
          check(controller.snapshot.active.lock === 305, "stock idle cycle blocks timer rewrite")
          fixture.command = ["/usr/bin/python3", controller.helper, "test-ac-active"]
          fixture.running = true
          phase++
        } else if (phase === 5) {
          controller.refresh(); phase++
        } else if (phase === 6) {
          if (controller.snapshot.pending) return
          check(controller.snapshot.active.lock === 905, "queued AC settings applied on activity")
          fixture.command = ["/usr/bin/python3", controller.helper, "test-status-error"]
          fixture.running = true; phase++
        } else if (phase === 7) {
          controller.refresh(); phase++
        } else if (phase === 8) {
          check(controller.statusError !== "", "status failure must be visible")
          fixture.command = ["/usr/bin/python3", controller.helper, "test-ac-active"]
          fixture.running = true; phase++
        } else if (phase === 9) {
          controller.refresh(); phase++
        } else if (phase === 10) {
          check(controller.statusError === "", "successful status must clear transient read error")
          controller.apply(controller.snapshot.preferences, "stale revision"); phase++
        } else if (phase === 11) {
          check(controller.error !== "", "action error must be visible")
          controller.refresh(); phase++
        } else if (phase === 12) {
          check(controller.error !== "", "status must preserve a failed action error")
          console.log("PASS: production IdleController with real isolated config backend and simulated charger/activity")
          Qt.quit()
        }
      } catch (error) { console.log("FAIL: " + error); Qt.quit() }
    }
  }
}
