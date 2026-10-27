import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Column {
  id: root
  LayoutMirroring.enabled: strings.rightToLeft
  LayoutMirroring.childrenInherit: true
  CareTranslations { id: strings; directory: Qt.resolvedUrl("i18n") }
  property int seconds: 150
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property bool custom: false
  readonly property bool valid: !custom || (minutes.acceptableInput && remainder.acceptableInput && customSeconds >= 1 && customSeconds <= 86400)
  readonly property int customSeconds: Number(minutes.text) * 60 + Number(remainder.text)
  property alias selector: selector
  signal edited(int value)
  signal editingStarted()
  signal focusMoved(var item)
  spacing: Style.space(4)

  function label(value) {
    if (value === 0) return strings.t("Immediately")
    if (value < 60) return strings.formatNumber(value) + "s"
    return strings.formatNumber(Math.floor(value / 60)) + "m" + (value % 60 ? " " + strings.formatNumber(value % 60) + "s" : "")
  }
  function reset(value) {
    custom = false
    seconds = value
    selector.value = String(value)
  }
  function open() { selector.open() }
  function close() { selector.close() }
  function updateCustom() { if (valid) { seconds = customSeconds; edited(seconds) } }
  TimeoutDropdown {
    id: selector
    width: parent.width
    showLabel: false
    foreground: root.foreground
    fontFamily: root.fontFamily
    value: String(root.seconds)
    options: {
      var values = [30, 60, 120, 150, 300, 600, 900, 1800, 3600]
      if (values.indexOf(root.seconds) < 0) values.push(root.seconds)
      values.sort(function(a, b) { return a - b })
      return values.map(function(v) { return {value: String(v), label: root.label(v)} }).concat([{value: "custom", label: strings.t("Custom…")}])
    }
    onChanged: function(value) {
      root.editingStarted()
      root.custom = value === "custom"
      if (root.custom) {
        minutes.text = String(Math.floor(root.seconds / 60))
        remainder.text = String(root.seconds % 60)
        minutes.forceActiveFocus()
      } else { root.seconds = Number(value); root.edited(root.seconds) }
    }
    onFocusEntered: root.focusMoved(selector)
  }
  Row {
    width: parent.width
    spacing: Style.space(4)
    visible: root.custom
    TextField {
      id: minutes
      width: (parent.width - parent.spacing) / 2
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      placeholderText: strings.t("min")
      validator: IntValidator { bottom: 0; top: 1440 }
      onTextEdited: { root.editingStarted(); root.updateCustom() }
      onActiveFocusChanged: if (activeFocus) root.focusMoved(minutes)
      Accessible.name: strings.t("Minutes")
    }
    TextField {
      id: remainder
      width: (parent.width - parent.spacing) / 2
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      placeholderText: strings.t("sec")
      validator: IntValidator { bottom: 0; top: 59 }
      onTextEdited: { root.editingStarted(); root.updateCustom() }
      onActiveFocusChanged: if (activeFocus) root.focusMoved(remainder)
      Accessible.name: strings.t("Seconds")
    }
  }
  Text { textFormat: Text.PlainText;
    visible: root.custom
    text: root.valid ? strings.t("minutes / seconds") : strings.t("Enter 1s–24h")
    color: root.valid ? root.foreground : Commons.Color.accent
    opacity: 0.7
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
