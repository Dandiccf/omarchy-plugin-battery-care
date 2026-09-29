import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower
import Quickshell.Wayland

Item {
  id: root
  property bool panelOpen: false
  property string helper: decodeURIComponent(Qt.resolvedUrl("idle_settings.py").toString().replace(/^file:\/\//, ""))
  property var snapshot: null
  property string error: ""
  property string statusError: ""
  property bool refreshQueued: false
  property bool monitorReady: false
  property bool activityAllowed: monitorReady && !activityMonitor.isIdle
  readonly property bool busy: process.running
  readonly property bool saving: busy && process.action === "apply"
  readonly property bool onBattery: UPower.onBattery
  signal saved()

  function refresh() {
    if (!enabled) return
    if (busy) { refreshQueued = true; return }
    execute("status", [])
  }
  function execute(action, extra) {
    if (!enabled || busy) return
    process.action = action
    process.received = false
    process.command = ["/usr/bin/python3", helper, action].concat(extra)
    process.running = true
  }
  function apply(preferences, revision) {
    if (busy) return
    error = ""
    execute("apply", ["--preferences", JSON.stringify(preferences), "--revision", revision].concat(activityAllowed ? ["--active", "--active-at", String(Date.now())] : []))
  }
  function synchronize() {
    if (!snapshot || !snapshot.managed || !snapshot.pending || snapshot.externalChange || !snapshot.safeToSwitch || !activityAllowed || busy) return
    execute("sync", ["--active", "--active-at", String(Date.now())])
  }
  onOnBatteryChanged: refresh()
  onActivityAllowedChanged: if (activityAllowed) refresh()
  onPanelOpenChanged: if (panelOpen) refresh()
  Component.onCompleted: refresh()

  IdleMonitor {
    id: activityMonitor
    enabled: root.enabled
    timeout: 1
    respectInhibitors: false
  }
  Timer { interval: 1500; running: root.enabled; onTriggered: root.monitorReady = true }
  Timer {
    interval: root.snapshot && root.snapshot.pending && !root.snapshot.externalChange && root.activityAllowed ? 1000 : root.panelOpen ? 5000 : 30000
    running: root.enabled
    repeat: true
    onTriggered: root.refresh()
  }
  Process {
    id: process
    property string action: "status"
    property bool received: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var response = JSON.parse(text)
          if (response.error) throw new Error(response.error)
          if (!response.preferences || !response.active || !response.revision) throw new Error("Incomplete idle response")
          root.snapshot = response
          process.received = true
          root.statusError = ""
          if (process.action !== "status") root.error = ""
          if (process.action === "apply") root.saved()
        } catch (error) {
          var message = String(error).replace(/^Error: /, "")
          if (process.action === "status") root.statusError = message
          else root.error = message
        }
      }
    }
    onExited: function(code) {
      if (code !== 0 || !received) {
        if (action === "status" && !root.statusError) root.statusError = "Could not read Screen & lock settings."
        else if (action !== "status" && !root.error) root.error = "Could not save Screen & lock settings."
      }
      var checkSwitch = received && action !== "sync"
      Qt.callLater(function() {
        if (root.refreshQueued) { root.refreshQueued = false; root.refresh() }
        else if (checkSwitch) root.synchronize()
      })
    }
  }
}
