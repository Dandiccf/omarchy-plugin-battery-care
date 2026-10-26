import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "Energy.js" as Energy

Panel {
  id: root
  CareTranslations { id: strings; directory: Qt.resolvedUrl("i18n") }
  moduleName: "omarchy.power"
  ipcTarget: "omarchy.power"
  manageIpc: false
  property var batteries: []
  property string selectedKey: ""
  property bool batteryPower: true
  property string errorText: ""
  property string actionError: ""
  property string stateError: ""
  property string guardWarning: ""
  property bool statusValid: false
  property int statusEpoch: 0
  property string profileError: ""
  property string profileReadError: ""
  property var profiles: []
  property string activeProfile: ""
  property int cursorIndex: 0
  property bool cursorActive: false
  property alias idleAutomationEnabled: idleController.enabled
  property alias screenSettings: screenSettings
  readonly property var battery: batteries.find(function(b) { return b.key === root.selectedKey }) || batteries[0] || ({})
  readonly property bool batteryPresent: batteries.length > 0
  readonly property bool busy: actionProc.running
  readonly property bool showPercentage: setting("showPercentage", true) === true
  property string helper: decodeURIComponent(Qt.resolvedUrl("battery.py").toString().replace(/^file:\/\//, ""))
  property string energyHelper: decodeURIComponent(Qt.resolvedUrl("energy.py").toString().replace(/^file:\/\//, ""))
  property var energyHistory: Energy.empty()
  property var flowHistory: ({})
  readonly property bool draining: statusValid && Model.draining(battery, batteryPower)
  property real drainNotifiedAt: 0
  // Warn once per episode, even with the panel closed; a charger that cannot keep up
  // otherwise goes unnoticed until the battery is empty.
  onDrainingChanged: {
    if (!draining || Date.now() - drainNotifiedAt < 600000) return
    drainNotifiedAt = Date.now()
    var watts = battery.rate > 0 ? battery.rate : Math.abs(battery.flow || 0)
    notifyProc.command = ["notify-send", "-u", "critical", "-a", "Battery Care", "-i", "battery-caution",
      strings.t("Charger is not keeping up"),
      strings.t("The charger is connected, but the battery is discharging at about %1 W. Check the charger, cable, and port.").arg(strings.formatNumber(watts, 1))]
    notifyProc.running = true
  }
  property string energyError: ""
  readonly property var energy: Energy.usage(energyHistory)
  readonly property real dischargeRate: {
    var total = 0
    batteries.forEach(function(b) { if (b.state === 2 && b.rate > 0) total += b.rate })
    return batteryPower && statusValid ? total : 0
  }
  readonly property real openPanelIndicatorWidth: showPercentage && !button.vertical ? button.glyphPaintedWidth : 0
  readonly property int controlCount: (battery.supported ? 2 : 0) + profiles.length
  readonly property var enabledControls: {
    var result = []
    if (!statusValid) return idleController.enabled ? [controlCount] : result
    if (battery.supported && !busy) {
      result.push(0)
      if (!batteryPower || Model.fullChargeActive(battery)) result.push(1)
    }
    if (!profileProc.running) {
      for (var i = 0; i < profiles.length; ++i) result.push(i + (battery.supported ? 2 : 0))
    }
    if (idleController.enabled) result.push(controlCount)
    return result
  }

  function refresh() {
    if (!batteryProc.running && !busy) {
      batteryProc.epoch = statusEpoch
      batteryProc.running = true
    }
    if (opened && !profilesProc.running) profilesProc.running = true
    if (!energyProc.running) energyProc.running = true
  }
  function receiveEnergy(raw) {
    try {
      var data = JSON.parse(raw)
      if (data.error) throw new Error(data.error)
      energyHistory = Energy.record(energyHistory, data, dischargeRate > 0 ? dischargeRate : null)
      energyError = ""
    } catch (e) {
      energyError = strings.t("Energy use is unavailable. %1").arg(String(e.message || e))
    }
  }
  function receive(raw, fromAction) {
    try {
      var data = JSON.parse(raw)
      if (data.error) {
        if (fromAction) actionError = data.error
        else errorText = data.error
        statusValid = false
        return
      }
      if (!Array.isArray(data.batteries) || typeof data.onBattery !== "boolean") throw new Error("Incomplete response")
      // Charger changes start a new net-power measurement.
      var tracked = Model.trackEnergy(data.onBattery === batteryPower ? flowHistory : ({}), data.batteries, Date.now())
      flowHistory = tracked.history
      batteries = data.batteries.map(function(b) { return Object.assign({}, b, {flow: tracked.flows[b.key] !== undefined ? tracked.flows[b.key] : null}) })
      batteryPower = data.onBattery
      stateError = data.stateError || ""
      guardWarning = data.guardWarning || ""
      statusValid = !stateError
      errorText = ""
    } catch (e) {
      statusValid = false
      if (fromAction) actionError = strings.t("Could not read action result. %1").arg(String(e))
      else errorText = strings.t("Could not read battery status. %1").arg(String(e))
    }
  }
  function charge(action) {
    if (!statusValid || busy || !battery.supported || (action === "full" && batteryPower)) return
    actionError = ""
    statusEpoch++
    actionProc.command = ["/usr/bin/python3", helper, action, "--battery", battery.key]
    actionProc.running = true
  }
  function setProfile(profile) {
    if (!statusValid || profileProc.running) return
    profileError = ""
    profileProc.command = ["omarchy-powerprofiles-set", batteryPower ? "battery" : "ac", profile]
    profileProc.running = true
  }
  function activateCursor() {
    if (enabledControls.indexOf(cursorIndex) < 0) return
    if (cursorIndex === controlCount) { screenSettings.toggle(); return }
    var offset = battery.supported ? 2 : 0
    if (offset && cursorIndex < 2) charge(cursorIndex === 0 ? Model.protectionAction(battery) : Model.fullChargeAction(battery))
    else if (profiles[cursorIndex - offset]) setProfile(profiles[cursorIndex - offset])
  }
  function selectBattery(delta) {
    if (batteries.length < 2 || busy) return
    var index = batteries.findIndex(function(b) { return b.key === root.battery.key })
    selectedKey = batteries[(index + delta + batteries.length) % batteries.length].key
    cursorActive = false
  }
  function revealControl(index) {
    var item = index === controlCount ? screenSettings : index === 0 && battery.supported ? protectButton
      : index === 1 && battery.supported ? fullButton
      : profileRepeater.itemAt(index - (battery.supported ? 2 : 0))
    revealItem(item)
  }
  function revealItem(item) {
    if (!item) return
    var y = item.mapToItem(column, 0, 0).y
    if (y < scroll.contentY) scroll.contentY = y
    else if (y + item.height > scroll.contentY + scroll.height) scroll.contentY = Math.min(y, y + item.height - scroll.height)
  }
  function togglePercentage() {
    settings = Object.assign({}, settings, {showPercentage: !showPercentage})
    if (bar && bar.shell) bar.shell.updateEntryInline(moduleName, settings)
  }
  IpcHandler {
    target: "omarchy.power"
    function open() { root.open() }
    function close() { root.close() }
    function show() { root.open() }
    function hide() { root.close() }
    function toggle() { root.toggle() }
    function togglePercentage() { root.togglePercentage() }
  }
  Component.onCompleted: refresh()
  onOpenedChanged: {
    if (opened) { refresh(); cursorActive = false; cursorIndex = 0; scroll.contentY = 0 }
    else screenSettings.cancel(true)
  }
  onSelectedKeyChanged: cursorActive = false
  visible: batteryPresent || errorText !== ""
  implicitWidth: visible ? button.implicitWidth : 0
  implicitHeight: visible ? button.implicitHeight : 0

  Process {
    id: batteryProc
    property int epoch: 0
    command: ["/usr/bin/python3", root.helper, "status"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: if (batteryProc.epoch === root.statusEpoch) root.receive(text, false) }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: if (text.trim() && batteryProc.epoch === root.statusEpoch) { root.errorText = text.trim(); root.statusValid = false } }
    onExited: function(code) { if (code !== 0 && batteryProc.epoch === root.statusEpoch) { root.statusValid = false; if (!root.errorText) root.errorText = "Battery status is unavailable. Check that Python and python-gobject are installed." } }
  }
  Process {
    id: actionProc
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.receive(text, true) }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: if (text.trim()) root.actionError = text.trim() }
    onExited: function(code) {
      if (code !== 0 && !root.actionError) root.actionError = "The charge setting could not be changed."
      Qt.callLater(root.refresh)
    }
  }
  Process { id: notifyProc }
  // Plugging in or unplugging updates the panel at once instead of at the next poll.
  Connections {
    target: UPower
    function onOnBatteryChanged() { root.refresh() }
  }
  Process {
    id: energyProc
    command: ["/usr/bin/python3", root.energyHelper]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: if (text.trim()) root.receiveEnergy(text) }
  }
  Process {
    id: profilesProc
    command: ["omarchy-powerprofiles-list", "--active-state"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = Model.parseProfiles(text)
        root.profiles = parsed.profiles
        root.activeProfile = parsed.activeProfile
        if (parsed.profiles.length) root.profileReadError = ""
      }
    }
    onExited: function(code) { if (code !== 0 || !root.profiles.length) { root.profiles = []; root.profileReadError = "Power profiles are unavailable." } }
  }
  Process {
    id: profileProc
    onExited: function(exitCode) {
      if (exitCode !== 0 && !root.profileError) root.profileError = "Could not change power profile."
      root.refresh()
    }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: root.profileError = text.trim() }
  }
  Timer { interval: root.opened ? 5000 : 30000; running: true; repeat: true; onTriggered: root.refresh() }
  IdleController { id: idleController; panelOpen: root.opened }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    readonly property bool separateLabel: "labelText" in button
    readonly property string percentageLabel: root.statusValid && root.showPercentage && !vertical ? Model.percent(root.battery.percentage, strings) : ""
    text: !root.statusValid ? "󰂃" : (separateLabel || !percentageLabel ? "" : percentageLabel + " ") + Model.batteryIcon(root.battery, root.batteryPower)
    Component.onCompleted: {
      if (separateLabel) button.labelText = Qt.binding(function() { return button.percentageLabel })
    }
    slotSize: Style.bar.iconSlot * (root.showPercentage && !vertical ? 2 : 1)
    tooltipText: root.statusValid ? strings.t("Battery Care · %1").arg(Model.status(root.battery, root.batteryPower, strings)) : strings.t("Battery Care · %1").arg(strings.t("Status unavailable"))
    onPressed: function(b) { if (b === Qt.RightButton) root.togglePercentage(); else root.toggle() }
  }
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(620))
    PanelKeyCatcher {
      id: keyCatcher
      LayoutMirroring.enabled: strings.rightToLeft
      LayoutMirroring.childrenInherit: true
      anchors.fill: parent
      blocked: screenSettings.expanded
      onMoveRequested: function(dx, dy) {
        root.cursorIndex = Model.nextControl(root.cursorIndex, dx || dy, root.enabledControls, root.cursorActive)
        root.cursorActive = true
        root.revealControl(root.cursorIndex)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(key) { if (key === "[") root.selectBattery(-1); else if (key === "]") root.selectBattery(1); else if (key === "d") root.actionError = ""; else if (key === "s") screenSettings.toggle() }
      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
      Column {
        id: column
        width: parent.width
        spacing: Style.space(14)
        Column {
          id: overview
          width: parent.width
          visible: !screenSettings.expanded
          spacing: Style.space(14)
        Row {
          width: parent.width
          spacing: Style.space(12)
          Text { textFormat: Text.PlainText;
            text: Model.batteryIcon(root.battery, root.batteryPower)
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.display
          }
          Column {
            width: parent.width - parent.children[0].implicitWidth - heroPercent.implicitWidth - parent.spacing * 2
            spacing: Style.space(4)
            Text { textFormat: Text.PlainText;
              width: parent.width
              text: "Battery Care"
              elide: Text.ElideRight
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Text { textFormat: Text.PlainText;
              width: parent.width
              text: root.statusValid ? Model.status(root.battery, root.batteryPower, strings) : strings.t("Status unavailable · showing last reading")
              color: root.bar.foreground
              opacity: 0.7
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
          Text { textFormat: Text.PlainText;
            id: heroPercent
            text: Model.percent(root.battery.percentage, strings)
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.displayLarge
            font.bold: true
          }
        }
        Flow {
          visible: root.batteries.length > 1
          width: parent.width
          spacing: Style.space(6)
          Repeater {
            model: root.batteries
            Button {
              required property var modelData
              text: modelData.native
              foreground: root.bar.foreground
              active: root.battery.key === modelData.key
              bordered: true
              enabled: !root.busy
              onClicked: root.selectedKey = modelData.key
            }
          }
        }
        Item {
          width: parent.width
          height: Style.space(8)
          Rectangle { anchors.fill: parent; radius: height / 2; color: root.bar.foreground; opacity: 0.15 }
          Rectangle {
            height: parent.height
            width: parent.width * Math.min(1, Math.max(0, (root.battery.percentage || 0) / 100))
            radius: height / 2
            color: root.bar.foreground
            Behavior on width { NumberAnimation { duration: 300 } }
          }
          Rectangle {
            visible: root.battery.enabled === true && root.battery.actualEnd !== null && root.battery.actualEnd < 100
            x: parent.width * (root.battery.actualEnd || 0) / 100 - width / 2
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height + Style.space(6)
            width: Style.space(2)
            color: Commons.Color.accent
          }
        }
        PanelSectionHeader { text: strings.t("CHARGE PROTECTION"); foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
        Grid {
          width: parent.width
          columns: width < Style.space(380) ? 1 : 2
          spacing: Style.space(8)
          visible: root.battery.supported === true
          CareButton {
            id: protectButton
            navigationOwner: root
            navigationIndex: 0
            width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
            text: strings.t(root.battery.enabled ? "%1 · On" : "%1 · Off").arg(Model.limitLabel(root.battery, strings))
            tooltipText: root.battery.enabled ? strings.t("Turn off the limit until you enable it again") : strings.t("Enable charge protection")
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            fontSize: Style.font.bodySmall
            bordered: true
            active: root.battery.enabled === true && !root.battery.mismatch
            enabled: !root.busy && root.statusValid
            opacity: enabled ? 1 : 0.5
            onClicked: root.charge(Model.protectionAction(root.battery))
          }
          CareButton {
            id: fullButton
            navigationOwner: root
            navigationIndex: 1
            width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
            text: Model.fullChargeActive(root.battery) ? strings.t("Cancel full charge") : strings.t("Charge fully once")
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            fontSize: Style.font.bodySmall
            bordered: true
            active: Model.fullChargeActive(root.battery)
            enabled: root.statusValid && !root.busy && (!root.batteryPower || Model.fullChargeActive(root.battery))
            opacity: enabled ? 1 : 0.5
            tooltipText: Model.fullChargeActive(root.battery) ? strings.t("Restore the charge limit now") : (root.batteryPower ? strings.t("Connect the charger first") : strings.t("Restore protection after unplugging"))
            onClicked: root.charge(Model.fullChargeAction(root.battery))
          }
        }
        Text { textFormat: Text.PlainText;
          width: parent.width
          text: root.busy ? strings.t("Applying charge setting…") : Model.explanation(root.battery, root.batteryPower, strings)
          color: root.bar.foreground
          opacity: 0.75
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }
        Text { textFormat: Text.PlainText;
          width: parent.width
          visible: text !== ""
          text: [root.errorText, root.draining ? "The charger is connected, but the battery is discharging. The charger may be too weak, or the cable or port may not deliver enough power." : "", root.stateError, root.actionError, root.battery.error, root.guardWarning, root.profileError, root.profileReadError].filter(function(x, i, a) { return x && a.indexOf(x) === i }).map(function(x) { return strings.t(x, x) }).join("\n")
          color: Commons.Color.accent
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap

        }
        Button {
          visible: root.actionError !== ""
          text: strings.t("Dismiss error (D)")
          foreground: root.bar.foreground
          onClicked: root.actionError = ""
        }
        PanelSeparator { foreground: root.bar.foreground }
        Grid {
          width: parent.width
          columns: width < Style.space(380) ? 1 : 2
          spacing: Style.space(18)
          Column {
            width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
            spacing: Style.space(8)
            InfoPair { label: strings.t("Battery health"); value: Model.percent(root.battery.health, strings) }
            InfoPair { label: strings.t("Charge cycles"); value: root.battery.cycles >= 0 ? strings.formatNumber(root.battery.cycles) : "—" }
            InfoPair { label: strings.t("Capacity"); value: root.battery.full > 0 ? strings.formatNumber(root.battery.full, 1) + " Wh" : "—" }
          }
          Column {
            width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
            spacing: Style.space(8)
            InfoPair { label: Model.flowLabel(root.battery, root.batteryPower, strings); value: Model.flowValue(root.battery, strings) }
            InfoPair {
              label: root.battery.state === 2 ? strings.t("Time left") : Model.stopLabel(root.battery, strings)
              value: Model.duration(root.battery.state === 2 ? root.battery.timeToEmpty : Model.timeToStop(root.battery), strings)
            }
            InfoPair { label: strings.t("Hardware cap"); value: root.battery.actualEnd != null ? Model.percent(root.battery.actualEnd, strings) : "—" }
          }
        }
        Text { textFormat: Text.PlainText;
          width: parent.width
          text: root.battery.model || ""

          visible: text !== ""
          color: root.bar.foreground
          opacity: 0.5
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
        PanelSeparator { foreground: root.bar.foreground }
        PanelSectionHeader { text: strings.t("USING SIGNIFICANT ENERGY"); foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
        Column {
          id: energyList
          width: parent.width
          spacing: Style.space(6)
          readonly property real maxImpact: root.energy.items.length ? root.energy.items[0].impact : 1
          Repeater {
            model: root.energy.items
            EnergyRow {
              required property var modelData
              name: modelData.name
              kind: modelData.kind === "app" ? "" : strings.t(modelData.kind === "system" ? "System service" : "Service")
              fraction: modelData.impact / energyList.maxImpact
              value: modelData.watts !== null && modelData.watts >= 0.05
                ? strings.t("≈ %1 W").arg(strings.formatNumber(modelData.watts, 1))
                : strings.formatNumber(Math.round(modelData.impact))
            }
          }
          Text { textFormat: Text.PlainText;
            width: parent.width
            visible: text !== ""
            text: root.energyError || (!root.energy.ready ? strings.t("Measuring energy use…")
              : !root.energy.items.length ? strings.t("No apps are using significant energy.") : "")
            color: root.energyError ? Commons.Color.accent : root.bar.foreground
            opacity: root.energyError ? 1 : 0.75
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }
          Text { textFormat: Text.PlainText;
            width: parent.width
            text: root.energy.watts
              ? strings.t("Estimated from CPU and GPU time over the last 3 minutes. Watts are battery drain above the recent idle level.")
              : strings.t("Impact is CPU and GPU time over the last 3 minutes; 100 is one fully busy core. Watt estimates appear after 5 minutes on battery.")
            wrapMode: Text.WordWrap
            color: root.bar.foreground
            opacity: 0.55
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
        PanelSeparator { foreground: root.bar.foreground }
        PanelSectionHeader { text: strings.t(root.batteryPower ? "POWER PROFILE · ON BATTERY" : "POWER PROFILE · PLUGGED IN"); foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
        Flow {
          width: parent.width
          spacing: Style.space(6)
          Repeater {
            id: profileRepeater
            model: root.profiles
            CareButton {
              required property var modelData
              required property int index
              navigationOwner: root
              navigationIndex: index + (root.battery.supported ? 2 : 0)
              width: parent.width < Style.space(380) ? parent.width : (parent.width - parent.spacing * Math.max(0, root.profiles.length - 1)) / Math.max(1, root.profiles.length)
              text: strings.t(String(modelData), String(modelData))
              iconText: Model.profileIcon(modelData)
              fontSize: Style.font.bodySmall
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: root.activeProfile === modelData
              enabled: root.statusValid && !profileProc.running
              onClicked: root.setProfile(modelData)
            }
          }
        }
        Text { textFormat: Text.PlainText;
          width: parent.width
          text: strings.t("Power profiles affect performance and energy use. Charge protection is independent.")
          wrapMode: Text.WordWrap
          color: root.bar.foreground
          opacity: 0.55
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
        PanelSeparator { foreground: root.bar.foreground }
        }
        ScreenSettings {
          id: screenSettings
          width: parent.width
          controller: idleController
          navigationOwner: root
          navigationIndex: root.controlCount
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          onExpandedChanged: scroll.contentY = 0
          onReveal: function(item) { Qt.callLater(function() { root.revealItem(item) }) }
          onReturnToPanel: { keyCatcher.forceActiveFocus(); root.cursorIndex = root.controlCount; root.cursorActive = true }
        }
      }
      }
    }
  }
  component EnergyRow: Row {
    property string name: ""
    property string kind: ""
    property real fraction: 0
    property string value: ""
    width: parent.width
    spacing: Style.space(8)
    Text { textFormat: Text.PlainText
      width: Math.round(parent.width * 0.45)
      text: kind ? name + " · " + kind : name
      elide: Text.ElideRight
      color: root.bar.foreground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Item {
      width: Math.max(0, parent.width - parent.children[0].width - parent.children[2].width - parent.spacing * 2)
      height: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      Rectangle { anchors.fill: parent; radius: height / 2; color: root.bar.foreground; opacity: 0.15 }
      Rectangle {
        height: parent.height
        width: Math.max(height, parent.width * Math.min(1, Math.max(0, fraction)))
        radius: height / 2
        color: root.bar.foreground
        opacity: 0.8
      }
    }
    Text { textFormat: Text.PlainText
      width: Style.space(64)
      horizontalAlignment: Text.AlignRight
      text: value
      color: root.bar.foreground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }
  component InfoPair: Row {
    property string label: ""
    property string value: ""
    width: parent.width
    spacing: Style.space(6)
    Text { textFormat: Text.PlainText; text: label; color: root.bar.foreground; opacity: 0.6; font.family: root.bar.fontFamily; font.pixelSize: Style.font.bodySmall }
    Item { width: Math.max(0, parent.width - parent.children[0].implicitWidth - parent.children[2].implicitWidth - parent.spacing * 2); height: 1 }
    Text { textFormat: Text.PlainText; text: value; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.bodySmall }
  }
}
