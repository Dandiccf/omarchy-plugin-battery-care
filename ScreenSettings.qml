import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Column {
  id: root
  LayoutMirroring.enabled: strings.rightToLeft
  LayoutMirroring.childrenInherit: true
  CareTranslations { id: strings; directory: Qt.resolvedUrl("i18n") }
  required property var controller
  property var navigationOwner: null
  property int navigationIndex: 0
  property color foreground: Commons.Color.foreground
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

  function duration(value) { return value === 0 ? strings.t("Immediately") : value < 60 ? strings.formatNumber(value) + "s" : strings.formatNumber(Math.floor(value / 60)) + "m" + (value % 60 ? " " + strings.formatNumber(value % 60) + "s" : "") }
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
    if (controller.saving) return
    var next = JSON.parse(JSON.stringify(draft))
    next[power][key] = seconds
    draft = next
    dirty = true
    message = ""
  }
  function toggleSeparate() {
    if (!draft || controller.saving) return
    var next = JSON.parse(JSON.stringify(draft))
    next.separate = !next.separate
    if (!next.separate) next.shared = Object.assign({}, next[snapshot.source])
    draft = next; dirty = true; message = ""; resetEditors()
  }
  function toggle() {
    if (controller.saving) return
    expanded = !expanded
    if (expanded) { resetDraft(); controller.refresh(); Qt.callLater(function() { if (root.draft) separateToggle.forceActiveFocus(); else root.forceActiveFocus(); root.reveal(root) }) }
    else cancel()
  }
  function cancel(force) {
    if (controller.saving && !force) return
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
    enabled: !root.controller.saving
    text: root.expanded ? strings.t("‹ Back · Screen & lock") : strings.t("Screen & lock · %1  ›").arg(root.snapshot ? (root.snapshot.source === "battery" ? strings.t("On battery") : strings.t("Plugged in")) : strings.t("Loading…"))
    onClicked: root.toggle()
  }
  Text { textFormat: Text.PlainText;
    width: parent.width
    text: root.snapshot ? strings.t("Screensaver %1 · Lock %2").arg(root.duration(root.snapshot.active.screensaver)).arg(root.duration(root.snapshot.active.lock)) : strings.t("Reading Omarchy idle settings…")
    color: root.foreground
    opacity: 0.7
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
  Text { textFormat: Text.PlainText;
    width: parent.width
    visible: text !== ""
    text: (root.controller.error ? strings.t(root.controller.error, root.controller.error) : "") || (root.controller.statusError ? strings.t(root.controller.statusError, root.controller.statusError) : "") || (root.snapshot && root.snapshot.warning ? strings.t(root.snapshot.warning, root.snapshot.warning) : "") || (root.snapshot && root.snapshot.externalChange ? strings.t("Timeouts changed elsewhere. Reload, then Apply to resume management.") : root.snapshot && root.snapshot.stayAwake ? strings.t("Paused by Stay Awake") : root.snapshot && root.snapshot.pending ? strings.t("Power-source settings will apply when you return.") : (root.message ? strings.t(root.message) : ""))
    color: Commons.Color.accent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap

  }
  Column {
    width: parent.width
    enabled: !root.controller.saving
    visible: root.expanded && root.draft !== null
    spacing: Style.space(10)
    Toggle {
      id: separateToggle
      width: parent.width
      label: strings.t("Separate power-source settings")
      description: strings.t("Use different timeouts on battery and plugged in")
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
          text: root.draft && root.draft.separate ? strings.t(root.snapshot.source === "battery" ? "ON BATTERY · Active" : "ON BATTERY") : strings.t("BOTH POWER SOURCES")
          color: root.snapshot && root.snapshot.source === "battery" ? Commons.Color.accent : root.foreground
        }
        Label { text: strings.t("Screensaver") }
        TimeoutEditor { id: batterySaver; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit(root.draft.separate ? "battery" : "shared", "screensaver", value) } onFocusMoved: function(item) { root.reveal(item) } }
        Label { text: strings.t("Lock screen") }
        TimeoutEditor { id: batteryLock; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit(root.draft.separate ? "battery" : "shared", "lock", value) } onFocusMoved: function(item) { root.reveal(item) } }
      }
      Column {
        width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
        visible: root.draft && root.draft.separate
        spacing: Style.space(6)
        Label { text: strings.t(root.snapshot && root.snapshot.source === "ac" ? "PLUGGED IN · Active" : "PLUGGED IN"); color: root.snapshot && root.snapshot.source === "ac" ? Commons.Color.accent : root.foreground }
        Label { text: strings.t("Screensaver") }
        TimeoutEditor { id: acSaver; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit("ac", "screensaver", value) } onFocusMoved: function(item) { root.reveal(item) } }
        Label { text: strings.t("Lock screen") }
        TimeoutEditor { id: acLock; width: parent.width; foreground: root.foreground; fontFamily: root.fontFamily; onEditingStarted: root.dirty = true; onEdited: function(value) { root.edit("ac", "lock", value) } onFocusMoved: function(item) { root.reveal(item) } }
      }
    }
    Text { textFormat: Text.PlainText;
      width: parent.width
      text: strings.t("Both times are measured from your last activity. Automatic switching waits for activity while you’re away.")
      color: root.foreground
      opacity: 0.65
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
    Flow {
      width: parent.width
      spacing: Style.space(6)
      Button { text: root.controller.saving ? strings.t("Saving…") : strings.t("Apply"); enabled: root.valid && root.needsApply && !root.controller.busy; opacity: enabled ? 1 : 0.5; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; bordered: true; focusable: true; onClicked: root.apply(); onActiveFocusChanged: if (activeFocus) root.reveal(this) }
      Button { text: strings.t("Cancel"); enabled: !root.controller.saving; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; bordered: true; focusable: true; onClicked: root.cancel(); onActiveFocusChanged: if (activeFocus) root.reveal(this) }
      Button { text: strings.t("Reload"); enabled: !root.controller.busy; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; focusable: true; onClicked: { root.dirty = false; root.controller.error = ""; root.resetDraft(); root.controller.refresh() } onActiveFocusChanged: if (activeFocus) root.reveal(this) }
    }
  }
  component Label: Text { textFormat: Text.PlainText;
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    width: parent.width
    wrapMode: Text.WordWrap
  }
}
