import QtQuick
import qs.Commons
import qs.Ui

Column {
  id: root
  required property var controller
  property var navigationOwner: null
  property int navigationIndex: 0
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property bool expanded: false
  property var draft: null
  property string draftRevision: ""
  property bool dirty: false
  property string message: ""
  readonly property var snapshot: controller.snapshot
  readonly property bool valid: draft && batterySaver.valid && batteryLock.valid && (!draft.separate || (acSaver.valid && acLock.valid))
  readonly property bool needsApply: dirty || (snapshot && snapshot.externalChange === true)
  signal reveal(var item)
  signal returnToPanel()
  spacing: Style.space(10)

  function duration(value) { return Math.floor(value / 60) + "m" + (value % 60 ? " " + value % 60 + "s" : "") }
  function resetDraft() {
    if (!snapshot) return
    draft = JSON.parse(JSON.stringify(snapshot.preferences))
    draftRevision = snapshot.revision
    dirty = false
    message = ""
    resetEditors()
  }
  function resetEditors() {
    if (!draft) return
    var left = draft[draft.separate ? "battery" : "shared"]
    batterySaver.reset(left.screensaver); batteryLock.reset(left.lock)
    acSaver.reset(draft.ac.screensaver); acLock.reset(draft.ac.lock)
  }
  function edit(power, key, seconds) {
    var next = JSON.parse(JSON.stringify(draft))
    next[power][key] = seconds
    draft = next
    dirty = true
    message = ""
  }
  function toggleSeparate() {
    var next = JSON.parse(JSON.stringify(draft))
    next.separate = !next.separate
    if (!next.separate) next.shared = Object.assign({}, next[snapshot.source])
    draft = next; dirty = true; message = ""; resetEditors()
  }
  function toggle() {
    expanded = !expanded
    if (expanded) { resetDraft(); controller.refresh(); Qt.callLater(function() { separateToggle.forceActiveFocus(); root.reveal(root) }) }
    else cancel()
  }
  function cancel() {
    batterySaver.close(); batteryLock.close(); acSaver.close(); acLock.close()
    resetDraft(); expanded = false; returnToPanel()
  }
  function apply() {
    if (!valid || !needsApply || controller.busy) return
    controller.apply(draft, draftRevision)
  }
  onSnapshotChanged: if (!dirty) resetDraft()
  Connections {
    target: root.controller
    function onSaved() { root.resetDraft(); root.message = root.snapshot.pending ? "Saved · applies when you return" : "Saved" }
  }
  Keys.onEscapePressed: function(event) { root.cancel(); event.accepted = true }
  CareButton {
    id: header
    width: parent.width
    navigationOwner: root.navigationOwner
    navigationIndex: root.navigationIndex
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.bodySmall
    bordered: true
    leftAlign: true
    focusable: root.expanded
    text: root.expanded ? "‹ Back · Screen & lock" : "Screen & lock · " + (root.snapshot ? (root.snapshot.source === "battery" ? "On battery" : "Plugged in") : "Loading…") + "  ›"
    onClicked: root.toggle()
  }
  Text {
    width: parent.width
    text: root.snapshot ? "Screensaver " + root.duration(root.snapshot.active.screensaver) + " · Lock " + root.duration(root.snapshot.active.lock) : "Reading Omarchy idle settings…"
    color: root.foreground
    opacity: 0.7
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
  Text {
    width: parent.width
    visible: text !== ""
    text: root.controller.error || (root.snapshot && root.snapshot.warning) || (root.snapshot && root.snapshot.externalChange ? "Timeouts changed elsewhere. Reload, then Apply to resume management." : root.snapshot && root.snapshot.stayAwake ? "Paused by Stay Awake" : root.snapshot && root.snapshot.pending ? "Power-source settings will apply when you return." : root.message)
    color: Color.accent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
  }
  Column {
    width: parent.width
    visible: root.expanded && root.draft !== null
    spacing: Style.space(10)
    Toggle {
      id: separateToggle
      width: parent.width
      label: "Separate power-source settings"
      description: "Use different timeouts on battery and plugged in"
      checked: root.draft ? root.draft.separate : false
      foreground: root.foreground
      fontFamily: root.fontFamily
      titleSize: Style.font.bodySmall
      onClicked: root.toggleSeparate()
      onActiveFocusChanged: if (activeFocus) root.reveal(this)
    }
    Grid {
      width: parent.width
      columns: root.draft && root.draft.separate && width >= Style.space(320) ? 2 : 1
      spacing: Style.space(12)
      Column {
        width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
        spacing: Style.space(6)
        Label {
          text: root.draft && root.draft.separate ? "ON BATTERY" + (root.snapshot.source === "battery" ? " · Active" : "") : "BOTH POWER SOURCES"
          color: root.snapshot && root.snapshot.source === "battery" ? Color.accent : root.foreground
        }
        Label { text: "Screensaver" }
        TimeoutEditor { id: batterySaver; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit(root.draft.separate ? "battery" : "shared", "screensaver", value) } onFocusMoved: function(item) { root.reveal(item) } }
        Label { text: "Lock screen" }
        TimeoutEditor { id: batteryLock; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit(root.draft.separate ? "battery" : "shared", "lock", value) } onFocusMoved: function(item) { root.reveal(item) } }
      }
      Column {
        width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
        visible: root.draft && root.draft.separate
        spacing: Style.space(6)
        Label { text: "PLUGGED IN" + (root.snapshot && root.snapshot.source === "ac" ? " · Active" : ""); color: root.snapshot && root.snapshot.source === "ac" ? Color.accent : root.foreground }
        Label { text: "Screensaver" }
        TimeoutEditor { id: acSaver; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit("ac", "screensaver", value) } onFocusMoved: function(item) { root.reveal(item) } }
        Label { text: "Lock screen" }
        TimeoutEditor { id: acLock; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit("ac", "lock", value) } onFocusMoved: function(item) { root.reveal(item) } }
      }
    }
    Text {
      width: parent.width
      text: "Both times are measured from your last activity. Automatic switching waits for activity while you’re away."
      color: root.foreground
      opacity: 0.65
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
    Flow {
      width: parent.width
      spacing: Style.space(6)
      Button { text: root.controller.saving ? "Saving…" : "Apply"; enabled: root.valid && root.needsApply && !root.controller.busy; opacity: enabled ? 1 : 0.5; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; bordered: true; focusable: true; onClicked: root.apply(); onActiveFocusChanged: if (activeFocus) root.reveal(this) }
      Button { text: "Cancel"; enabled: !root.controller.saving; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; bordered: true; focusable: true; onClicked: root.cancel(); onActiveFocusChanged: if (activeFocus) root.reveal(this) }
      Button { text: "Reload"; enabled: !root.controller.busy; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; focusable: true; onClicked: { root.dirty = false; root.controller.error = ""; root.resetDraft(); root.controller.refresh() } onActiveFocusChanged: if (activeFocus) root.reveal(this) }
    }
  }
  component Label: Text {
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    width: parent.width
    wrapMode: Text.WordWrap
  }
}
