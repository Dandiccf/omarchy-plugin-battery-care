import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Energy.js" as Energy

// Battery history: 24 hours in 15-minute slots or the last 10 days, with the apps
// that used the most energy on battery. Data comes from the panel's sampler.
Column {
  id: root
  LayoutMirroring.enabled: strings.rightToLeft
  LayoutMirroring.childrenInherit: true
  CareTranslations { id: strings; directory: Qt.resolvedUrl("i18n") }
  property var navigationOwner: null
  property int navigationIndex: 0
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property bool expanded: false
  property bool recording: true
  property var buckets: []
  property real now: Date.now() / 1000
  property string error: ""
  property bool week: false
  readonly property var slots: Energy.daySlots(buckets, now)
  readonly property var days: Energy.weekDays(buckets, now)
  readonly property var apps: Energy.topApps(buckets, week ? days[0].start : now - 86400, 6)
  readonly property real maxWatts: Math.max.apply(null, slots.map(function(s) { return s.watts || 0 }).concat([1]))
  readonly property real maxWh: Math.max.apply(null, days.map(function(d) { return d.wh }).concat([1]))
  readonly property var today: days[days.length - 1]
  readonly property bool hasWatts: slots.some(function(s) { return s.watts > 0 })
  readonly property bool hasWh: days.some(function(d) { return d.wh > 0 })
  signal opened()
  signal recordingToggled()
  signal clearRequested()
  signal reveal(var item)
  signal returnToPanel()
  spacing: Style.space(10)

  function toggle() {
    expanded = !expanded
    if (expanded) { opened(); Qt.callLater(function() { header.forceActiveFocus(); root.reveal(root) }) }
    else returnToPanel()
  }
  function close() { if (expanded) { expanded = false; returnToPanel() } }
  function duration(seconds) {
    var minutes = Math.round(seconds / 60)
    return minutes >= 60 ? strings.formatNumber(Math.floor(minutes / 60)) + "h " + strings.formatNumber(minutes % 60) + "m" : strings.formatNumber(minutes) + "m"
  }
  function clock(epoch) { return Qt.locale().toString(new Date(epoch * 1000), Qt.locale().timeFormat(Locale.ShortFormat)) }
  Keys.onEscapePressed: function(event) { root.close(); event.accepted = true }

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
    text: root.expanded ? strings.t("‹ Back · Battery history") : strings.t("Battery history  ›")
    onClicked: root.toggle()
  }
  Text { textFormat: Text.PlainText;
    width: parent.width
    text: root.error ? strings.t("History is unavailable. %1").arg(root.error)
      : !root.recording ? strings.t("Recording is off.")
      : strings.t("Today on battery: %1 · %2 Wh").arg(root.duration(root.today.battery)).arg(strings.formatNumber(root.today.wh, 1))
    color: root.error ? Commons.Color.accent : root.foreground
    opacity: root.error ? 1 : 0.7
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
  Column {
    width: parent.width
    visible: root.expanded
    spacing: Style.space(10)
    Row {
      spacing: Style.space(6)
      Button { text: strings.t("24 hours"); active: !root.week; bordered: true; focusable: true; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; onClicked: root.week = false; onActiveFocusChanged: if (activeFocus) root.reveal(this) }
      Button { text: strings.t("10 days"); active: root.week; bordered: true; focusable: true; foreground: root.foreground; fontFamily: root.fontFamily; fontSize: Style.font.bodySmall; onClicked: root.week = true; onActiveFocusChanged: if (activeFocus) root.reveal(this) }
    }

    // 24 hours: battery level and power use per 15 minutes.
    Column {
      width: parent.width
      visible: !root.week
      spacing: Style.space(6)
      Label { text: strings.t("BATTERY LEVEL"); opacity: 0.7 }
      Chart {
        model: root.slots
        maximum: 100
        value: function(s) { return s.level }
        highlight: function(s) { return s.plugged }
      }
      Axis { labels: [root.clock(root.slots[0].start), root.clock(root.slots[48].start), strings.t("Now")] }
      Row {
        spacing: Style.space(12)
        Legend { text: strings.t("On battery"); swatch: root.foreground }
        Legend { text: strings.t("Plugged in"); swatch: Commons.Color.accent }
      }
      Label { text: root.hasWatts ? strings.t("POWER USE ON BATTERY · up to %1 W").arg(strings.formatNumber(root.maxWatts, 1)) : strings.t("POWER USE ON BATTERY"); opacity: 0.7 }
      Chart {
        model: root.slots
        maximum: root.maxWatts
        value: function(s) { return s.watts }
        highlight: function(s) { return false }
      }
      Axis { labels: [root.clock(root.slots[0].start), root.clock(root.slots[48].start), strings.t("Now")] }
    }

    // 10 days: energy drawn from the battery per day.
    Column {
      width: parent.width
      visible: root.week
      spacing: Style.space(6)
      Label { text: root.hasWh ? strings.t("BATTERY ENERGY USED PER DAY · up to %1 Wh").arg(strings.formatNumber(root.maxWh, 1)) : strings.t("BATTERY ENERGY USED PER DAY"); opacity: 0.7 }
      Chart {
        model: root.days
        maximum: root.maxWh
        value: function(d) { return d.wh > 0 ? d.wh : null }
        highlight: function(d) { return false }
      }
      Row {
        width: parent.width
        Repeater {
          model: root.days
          Text { textFormat: Text.PlainText
            required property var modelData
            width: parent.width / root.days.length
            horizontalAlignment: Text.AlignHCenter
            text: Qt.locale().dayName(new Date(modelData.start * 1000).getDay(), Locale.ShortFormat)
            color: root.foreground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }

    Label { text: strings.t(root.week ? "APPS ON BATTERY · 10 DAYS" : "APPS ON BATTERY · 24 HOURS"); opacity: 0.7 }
    Repeater {
      model: root.apps
      Row {
        required property var modelData
        width: parent.width
        spacing: Style.space(8)
        Text { textFormat: Text.PlainText
          width: Math.round(parent.width * 0.45)
          text: modelData.kind === "app" ? modelData.name : modelData.name + " · " + strings.t(modelData.kind === "system" ? "System service" : "Service")
          elide: Text.ElideRight
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Item {
          width: Math.max(0, parent.width - parent.children[0].width - parent.children[2].width - parent.spacing * 2)
          height: Style.space(6)
          anchors.verticalCenter: parent.verticalCenter
          Rectangle { anchors.fill: parent; radius: height / 2; color: root.foreground; opacity: 0.15 }
          Rectangle {
            height: parent.height
            width: Math.max(height, parent.width * Math.min(1, modelData.cores / root.apps[0].cores))
            radius: height / 2
            color: root.foreground
            opacity: 0.8
          }
        }
        Text { textFormat: Text.PlainText
          width: Style.space(48)
          horizontalAlignment: Text.AlignRight
          text: strings.formatNumber(Math.round(modelData.share * 100)) + "%"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
    Label {
      visible: root.apps.length === 0
      text: strings.t("No battery use recorded yet.")
      opacity: 0.75
    }
    Toggle {
      width: parent.width
      label: strings.t("Record battery history")
      description: strings.t("Stored only on this device for 10 days, in 15-minute steps, including app names.")
      checked: root.recording
      foreground: root.foreground
      fontFamily: root.fontFamily
      titleSize: Style.font.bodySmall
      onClicked: root.recordingToggled()
      onActiveFocusChanged: if (activeFocus) root.reveal(this)
    }
    Button {
      text: strings.t("Clear history")
      enabled: root.buckets.length > 0
      opacity: enabled ? 1 : 0.5
      bordered: true
      focusable: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      onClicked: root.clearRequested()
      onActiveFocusChanged: if (activeFocus) root.reveal(this)
    }
    Label {
      text: strings.t("App shares are CPU and GPU time on battery. Gaps mean the laptop was asleep, off, or the shell was not running.")
      opacity: 0.55
    }
  }

  component Label: Text { textFormat: Text.PlainText;
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    width: parent.width
    wrapMode: Text.WordWrap
  }
  component Chart: Item {
    id: chart
    property var model: []
    property real maximum: 1
    property var value: function(item) { return null }
    property var highlight: function(item) { return false }
    width: parent.width
    height: Style.space(56)
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.foreground; opacity: 0.2 }
    Row {
      anchors.fill: parent
      Repeater {
        model: chart.model
        Item {
          required property var modelData
          width: chart.width / Math.max(1, chart.model.length)
          height: chart.height
          readonly property var amount: chart.value(modelData)
          Rectangle {
            visible: parent.amount !== null && parent.amount !== undefined
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.max(1, parent.width - (parent.width > 6 ? 2 : 1))
            height: Math.max(1, chart.height * Math.min(1, (parent.amount || 0) / Math.max(chart.maximum, 0.001)))
            radius: Math.min(2, width / 2)
            color: chart.highlight(parent.modelData) ? Commons.Color.accent : root.foreground
            opacity: 0.85
          }
        }
      }
    }
  }
  component Axis: Row {
    property var labels: []
    width: parent.width
    Repeater {
      model: parent.labels
      Text { textFormat: Text.PlainText
        required property var modelData
        required property int index
        width: parent.width / parent.labels.length
        horizontalAlignment: index === 0 ? Text.AlignLeft : index === parent.labels.length - 1 ? Text.AlignRight : Text.AlignHCenter
        text: modelData
        color: root.foreground
        opacity: 0.55
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
  component Legend: Row {
    property string text: ""
    property color swatch: root.foreground
    spacing: Style.space(4)
    Rectangle { width: Style.space(8); height: Style.space(8); radius: 2; color: parent.swatch; anchors.verticalCenter: parent.verticalCenter }
    Text { textFormat: Text.PlainText; text: parent.text; color: root.foreground; opacity: 0.7; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
  }
}
