// Turns cumulative energy.py counters into recent per-app energy impact.
// Impact is CPU plus GPU busy time: 100 means one core (or engine) fully busy.
var WINDOW = 180
var POWER_WINDOW = 1800
var MIN_SPAN = 4
var MIN_BASELINE = 300
var SIGNIFICANT = 5
var LIMIT = 5

function empty() { return { samples: [], power: [] } }

function valid(sample) {
  return sample && typeof sample.time === "number" && isFinite(sample.time) && Array.isArray(sample.units)
}

// Returns a new history; rate is the battery discharge rate in watts, or null on AC.
function record(history, sample, rate) {
  if (!valid(sample)) return history
  var samples = (history.samples || []).filter(function(s) { return s.time < sample.time })
  samples.push(sample)
  // Keep the newest sample at or before the window start as the baseline.
  var start = sample.time - WINDOW
  var first = 0
  for (var i = 0; i < samples.length; ++i) if (samples[i].time <= start) first = i
  samples = samples.slice(first)
  var power = (history.power || []).filter(function(p) { return p.time < sample.time && p.time >= sample.time - POWER_WINDOW })
  // A gap without readings (AC power, suspend) starts a new baseline.
  if (typeof rate !== "number" || !isFinite(rate) || rate <= 0) power = []
  else power.push({ time: sample.time, rate: rate })
  return { samples: samples, power: power }
}

function delta(now, then) { return now > then ? now - then : 0 }

function usage(history) {
  var samples = history.samples || []
  if (samples.length < 2) return { ready: false, items: [], seconds: 0, watts: false }
  var oldest = samples[0], newest = samples[samples.length - 1]
  var seconds = newest.time - oldest.time
  if (seconds < MIN_SPAN) return { ready: false, items: [], seconds: seconds, watts: false }
  var before = {}
  oldest.units.forEach(function(u) { before[u.id] = u })
  var clock = typeof newest.gpuClock === "number" && typeof oldest.gpuClock === "number" ? delta(newest.gpuClock, oldest.gpuClock) : 0
  var groups = {}, total = 0
  newest.units.forEach(function(u) {
    var old = before[u.id] || { cpu: 0, gpuNs: 0, gpuCycles: 0 }
    var cpu = delta(u.cpu, old.cpu) / 1e6 / seconds
    var gpu = delta(u.gpuNs || 0, old.gpuNs || 0) / 1e9 / seconds
    if (clock > 0) gpu += delta(u.gpuCycles || 0, old.gpuCycles || 0) / clock
    var key = u.kind + "\n" + u.name
    var g = groups[key] || (groups[key] = { name: String(u.name), kind: String(u.kind), cpu: 0, gpu: 0 })
    g.cpu += cpu
    g.gpu += gpu
    total += cpu + gpu
  })
  var dynamic = activePower(history.power || [], oldest.time)
  var items = Object.keys(groups).map(function(k) {
    var g = groups[k]
    g.impact = (g.cpu + g.gpu) * 100
    g.watts = dynamic !== null && total > 0 ? dynamic * (g.cpu + g.gpu) / total : null
    return g
  }).filter(function(g) { return g.impact >= SIGNIFICANT })
  items.sort(function(a, b) { return b.impact - a.impact || (a.name < b.name ? -1 : 1) })
  return { ready: true, items: items.slice(0, LIMIT), seconds: seconds, watts: dynamic !== null }
}

// Discharge above the lowest recent rate, which approximates display and idle power.
// Needs several minutes of uninterrupted battery readings to be meaningful.
function activePower(power, since) {
  if (power.length < 2 || power[power.length - 1].time - power[0].time < MIN_BASELINE) return null
  var floor = Math.min.apply(null, power.map(function(p) { return p.rate }))
  var recent = power.filter(function(p) { return p.time >= since })
  if (!recent.length) return null
  var average = recent.reduce(function(sum, p) { return sum + p.rate }, 0) / recent.length
  return Math.max(0, average - floor)
}

if (typeof module !== "undefined") module.exports = { WINDOW, SIGNIFICANT, LIMIT, empty, record, usage, activePower }
