// Battery state numbers are UPower's documented DeviceState enum.
function duration(seconds, i18n) {
  function number(value) { return i18n ? i18n.formatNumber(value) : String(value) }
  if (!(seconds > 0)) return "—"
  var minutes = Math.max(1, Math.round(seconds / 60))
  return minutes >= 60 ? number(Math.floor(minutes / 60)) + "h " + number(minutes % 60) + "m" : number(minutes) + "m"
}
function percent(value, i18n) { return typeof value === "number" && isFinite(value) ? (i18n ? i18n.formatNumber(Math.round(value)) : Math.round(value)) + "%" : "—" }
function limitLabel(b, strings) { return b.end != null ? (strings ? strings.t("%1% limit").replace("%1", b.end) : b.end + "% limit") : (strings ? strings.t("Protect battery") : "Protect battery") }
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
function status(b, onBattery, strings) {
  function t(key) { return strings ? strings.t(key) : key }
  if (!b || !b.key) return t("Reading battery…")
  if (b.mismatch) return t("Charge setting mismatch")
  if (draining(b, onBattery)) return t("Plugged in · battery draining")
  if (b.state === 2) return t("On battery")
  if (holding(b, onBattery)) return t("Plugged in · charge paused")
  if (b.state === 1) return b.enabled ? t("Charging · protection on") : t("Charging to full")
  if (b.state === 4 && b.percentage >= 99) return t("Fully charged")
  if (b.state === 3) return t("Empty")
  if (b.state === 5) return onBattery ? t("Charging paused") : t("Plugged in · charge paused")
  if (b.state === 6) return t("Discharge pending")
  return onBattery ? t("On battery") : t("Plugged in · idle")
}
function explanation(b, onBattery, strings) {
  function t(key) { return strings ? strings.t(key) : key }
  if (!b || !b.key) return t("Reading battery information…")
  if (!b.supported) return t("Charge controls are not available for this battery. Monitoring still works.")
  if (b.mismatch) return t("The hardware limit differs from UPower. Another battery manager may be changing it.")
  if (b.mode === "full" && !b.enabled) return t("Full charge for this session. Protection returns after unplugging (checked every 15 seconds), or at the next login after a reboot.")
  if (b.mode === "off" && !b.enabled) return t("Protection is off. Charging to 100% is allowed until you turn the limit on again.")
  if (b.enabled) {
    var text = b.end != null ? t("Stops charging at %1%.").replace("%1", b.end) : t("Uses the battery’s firmware charge limit.")
    if (b.start != null && b.start > 0) text += " " + t("Resumes below %1%.").replace("%1", b.start)
    if (b.end != null && b.percentage > b.end) text += t(" It will not actively drain the battery.")
    return text
  }
  return b.end != null ? t("Protection is off. The available %1% preset is not active.").replace("%1", b.end) : t("Protection is off. Enable protection to use the firmware limit.")
}
// Net battery power measured from stored-energy changes, for firmware that reports
// 0 W. Readings span at least 30 s and at most 5 min; positive means charging.
var FLOW_MIN = 30000
var FLOW_MAX = 300000
function trackEnergy(history, batteries, now) {
  var next = {}, flows = {}
  ;(batteries || []).forEach(function(b) {
    if (!b.key || typeof b.energy !== "number" || !isFinite(b.energy)) return
    var readings = ((history || {})[b.key] || []).filter(function(r) { return r.time < now && now - r.time <= FLOW_MAX })
    var base = null
    readings.forEach(function(r) { if (now - r.time >= FLOW_MIN) base = r })
    readings.push({ time: now, energy: b.energy })
    next[b.key] = readings
    if (base) flows[b.key] = (b.energy - base.energy) * 3600000 / (now - base.time)
  })
  return { history: next, flows: flows }
}
// A charger that cannot cover the load: plugged in, yet the battery loses energy.
function draining(b, onBattery) {
  if (onBattery || !b) return false
  return (b.state === 2 && b.rate > 1) || (typeof b.flow === "number" && b.flow < -1)
}
function flowLabel(b, onBattery, strings) {
  function t(key) { return strings ? strings.t(key) : key }
  if (onBattery && b.state === 2) return t("Power use")
  if (draining(b, onBattery)) return t("Battery drain")
  if (b.state === 1) return t("Into battery")
  return t("Power flow")
}
function flowValue(b, i18n) {
  function number(value) { return i18n ? i18n.formatNumber(value, 1) : value.toFixed(1) }
  var measured = typeof b.flow === "number" && isFinite(b.flow) ? Math.abs(b.flow) : null
  if (b.rate > 0) return number(b.rate) + " W"
  if (measured !== null && measured >= 0.5) return "≈ " + number(measured) + " W"
  return b.rate != null ? number(b.rate) + " W" : "—"
}
// Time until charging stops: at the active limit, otherwise UPower's time to full.
function timeToStop(b) {
  if (!b || b.state !== 1) return 0
  if (!(b.enabled === true && b.end != null && b.end < 100)) return b.timeToFull > 0 ? b.timeToFull : 0
  var rate = b.rate > 0 ? b.rate : (b.flow > 0.5 ? b.flow : 0)
  if (!(rate > 0 && b.full > 0 && typeof b.energy === "number")) return 0
  var remaining = b.full * b.end / 100 - b.energy
  return remaining > 0 ? remaining / rate * 3600 : 0
}
function stopLabel(b, strings) {
  var limited = b && b.enabled === true && b.end != null && b.end < 100
  if (!limited) return strings ? strings.t("Time to full") : "Time to full"
  return (strings ? strings.t("Time to %1%") : "Time to %1%").replace("%1", b.end)
}
function batteryIcon(b, onBattery) {
  var icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
  if (b.state === 1 && !onBattery) return "󰂄"
  if (!onBattery) return "󰚥"
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
if (typeof module !== "undefined") module.exports = { timeToStop, stopLabel, trackEnergy, draining, flowLabel, flowValue, duration, percent, limitLabel, protectionAction, fullChargeActive, fullChargeAction, nextControl, holding, status, explanation, batteryIcon, profileIcon, parseProfiles }
