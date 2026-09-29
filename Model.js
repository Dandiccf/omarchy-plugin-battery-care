// Battery state numbers are UPower's documented DeviceState enum.
function duration(seconds) {
  if (!(seconds > 0)) return "—"
  var minutes = Math.max(1, Math.round(seconds / 60))
  return minutes >= 60 ? Math.floor(minutes / 60) + "h " + (minutes % 60) + "m" : minutes + "m"
}
function percent(value) { return typeof value === "number" && isFinite(value) ? Math.round(value) + "%" : "—" }
function limitLabel(b) { return b.end !== null && b.end !== undefined ? b.end + "% limit" : "Protect battery" }
function protectionAction(b) { return b.enabled === true ? "off" : "protect" }
function fullChargeActive(b) { return b.mode === "full" && b.enabled === false }
function fullChargeAction(b) { return fullChargeActive(b) ? "protect" : "full" }
function nextControl(index, delta, enabled, active) {
  if (!enabled.length) return -1
  if (!active) return enabled[0]
  var position = enabled.indexOf(index)
  if (position < 0) return enabled[0]
  return enabled[Math.max(0, Math.min(enabled.length - 1, position + delta))]
}
function holding(b, onBattery) {
  return !onBattery && b.enabled === true && !b.mismatch && (b.state === 4 || b.state === 5)
}
function status(b, onBattery) {
  if (!b || !b.key) return "Reading battery…"
  if (b.mismatch) return "Charge setting mismatch"
  if (b.state === 2) return "On battery"
  if (holding(b, onBattery)) return "Holding · protection on"
  if (b.state === 1) return b.enabled ? "Charging · protection on" : "Charging to full"
  if (b.state === 4 && b.percentage >= 99) return "Fully charged"
  if (b.state === 3) return "Empty"
  if (b.state === 5) return "Charging paused"
  if (b.state === 6) return "Discharge pending"
  return onBattery ? "On battery" : "Connected · idle"
}
function explanation(b, onBattery) {
  if (!b || !b.key) return "Reading battery information…"
  if (!b.supported) return "Charge controls are not available for this battery. Monitoring still works."
  if (b.mismatch) return "The hardware limit differs from UPower. Another battery manager may be changing it."
  if (b.mode === "full" && !b.enabled) return "Full charge for this session. Protection returns after unplugging (checked every 15 seconds), or at the next login after a reboot."
  if (b.mode === "off" && !b.enabled) return "Protection is off. Charging to 100% is allowed until you turn the limit on again."
  if (b.enabled) {
    var text = b.end != null ? "Stops charging at " + b.end + "%." : "Uses the battery’s firmware charge limit."
    if (b.start != null && b.start > 0) text += " Resumes below " + b.start + "%."
    if (b.end != null && b.percentage > b.end) text += " It will not actively drain the battery."
    return text
  }
  return "Protection is off. " + (b.end != null ? "The available " + b.end + "% preset is not active." : "Enable protection to use the firmware limit.")
}
function batteryIcon(b, onBattery) {
  var icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
  if (b.state === 1 && !onBattery) return "󰂄"
  return icons[Math.max(0, Math.min(9, Math.floor((b.percentage || 0) / 10)))]
}
function profileIcon(name) {
  return name === "power-saver" ? "󰌪" : name === "performance" ? "󰓅" : "󰊚"
}
function parseProfiles(raw) {
  var profiles = [], active = ""
  String(raw || "").split("\n").forEach(function(line) {
    var p = line.trim().split("\t")
    if (p[0]) { profiles.push(p[0]); if (p[1] === "1") active = p[0] }
  })
  return { profiles: profiles, activeProfile: active }
}
if (typeof module !== "undefined") module.exports = { duration, percent, limitLabel, protectionAction, fullChargeActive, fullChargeAction, nextControl, holding, status, explanation, batteryIcon, profileIcon, parseProfiles }
