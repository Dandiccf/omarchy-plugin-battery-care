// Turns cumulative energy.py counters into recent per-app energy impact.
// Impact is CPU plus GPU busy time: 100 means one core (or engine) fully busy.
var WINDOW = 180
var POWER_WINDOW = 1800
var MIN_SPAN = 4
var MIN_BASELINE = 300
var SIGNIFICANT = 5
var LIMIT = 5
// Laptop power model, learned on battery where total power is measurable:
// watts = base + perCore * activity. Weights are in 30-second units.
var DECAY = 0.998
var MIN_WEIGHT = 20
var MAX_PER_CORE = 30

function empty() { return { samples: [], power: [], model: null, learned: false } }

function valid(sample) {
  return sample && typeof sample.time === "number" && isFinite(sample.time) && Array.isArray(sample.units)
}

// Returns a new history; rate is the battery discharge rate in watts, or null on AC.
function record(history, sample, rate) {
  if (!valid(sample)) return history
  var samples = (history.samples || []).filter(function(s) { return s.time < sample.time })
  var previous = samples.length ? samples[samples.length - 1] : null
  var model = history.model || validModel(sample.model)
  var learned = false
  var battery = typeof rate === "number" && isFinite(rate) && rate > 0
  // Learn only from short, uninterrupted battery intervals.
  if (battery && previous && sample.time - previous.time >= 2 && sample.time - previous.time <= 120
      && (history.power || []).length) {
    var seconds = sample.time - previous.time
    model = learn(model, activity(previous, sample), rate, seconds / 30)
    learned = true
  }
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
  return { samples: samples, power: power, model: model, learned: learned }
}

function validModel(m) {
  if (!m || typeof m !== "object") return null
  var keys = ["w", "a", "p", "aa", "ap"]
  for (var i = 0; i < keys.length; ++i) if (typeof m[keys[i]] !== "number" || !isFinite(m[keys[i]]) || m[keys[i]] < 0) return null
  return { w: m.w, a: m.a, p: m.p, aa: m.aa, ap: m.ap }
}

function learn(model, load, watts, weight) {
  var m = model || { w: 0, a: 0, p: 0, aa: 0, ap: 0 }
  var d = Math.pow(DECAY, weight)
  return { w: m.w * d + weight, a: m.a * d + weight * load, p: m.p * d + weight * watts,
           aa: m.aa * d + weight * load * load, ap: m.ap * d + weight * load * watts }
}

// Least-squares fit; with too little variation in load, power is treated as flat.
function fit(m) {
  if (!m || m.w < MIN_WEIGHT) return null
  var meanA = m.a / m.w, meanP = m.p / m.w
  var variance = m.aa / m.w - meanA * meanA
  var perCore = variance > 0.0025 ? (m.ap / m.w - meanA * meanP) / variance : 0
  perCore = Math.max(0, Math.min(MAX_PER_CORE, perCore))
  var base = meanP - perCore * meanA
  if (base < 0) { base = 0; perCore = meanA > 0 ? meanP / meanA : 0 }
  return { base: base, perCore: perCore }
}

// Total CPU plus GPU activity in busy cores between two samples.
function activity(older, newer) {
  var seconds = newer.time - older.time
  if (!(seconds > 0)) return 0
  var before = {}
  older.units.forEach(function(u) { before[u.id] = u })
  var clock = typeof newer.gpuClock === "number" && typeof older.gpuClock === "number" ? delta(newer.gpuClock, older.gpuClock) : 0
  var total = 0
  newer.units.forEach(function(u) {
    var old = before[u.id] || { cpu: 0, gpuNs: 0, gpuCycles: 0 }
    total += delta(u.cpu, old.cpu) / 1e6 / seconds + delta(u.gpuNs || 0, old.gpuNs || 0) / 1e9 / seconds
    if (clock > 0) total += delta(u.gpuCycles || 0, old.gpuCycles || 0) / clock
  })
  return total
}

// Estimated whole-laptop power at the recent activity level, or null until learned.
function laptopPower(history) {
  var model = fit(history.model)
  var samples = history.samples || []
  if (!model || samples.length < 2) return null
  var oldest = samples[0], newest = samples[samples.length - 1]
  if (newest.time - oldest.time < MIN_SPAN) return null
  return model.base + model.perCore * activity(oldest, newest)
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

if (typeof module !== "undefined") module.exports = { WINDOW, SIGNIFICANT, LIMIT, MIN_WEIGHT, empty, record, usage, activePower, validModel, learn, fit, activity, laptopPower }
