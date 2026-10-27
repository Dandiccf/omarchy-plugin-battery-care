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

// CPU and GPU activity in busy cores between two samples, grouped by app name.
function groups(older, newer) {
  var seconds = newer.time - older.time
  var result = {}
  if (!(seconds > 0)) return result
  var before = {}
  older.units.forEach(function(u) { before[u.id] = u })
  var clock = typeof newer.gpuClock === "number" && typeof older.gpuClock === "number" ? delta(newer.gpuClock, older.gpuClock) : 0
  newer.units.forEach(function(u) {
    var old = before[u.id] || { cpu: 0, gpuNs: 0, gpuCycles: 0 }
    var cpu = delta(u.cpu, old.cpu) / 1e6 / seconds
    var gpu = delta(u.gpuNs || 0, old.gpuNs || 0) / 1e9 / seconds
    if (clock > 0) gpu += delta(u.gpuCycles || 0, old.gpuCycles || 0) / clock
    var key = u.kind + "\n" + u.name
    var g = result[key] || (result[key] = { name: String(u.name), kind: String(u.kind), cpu: 0, gpu: 0 })
    g.cpu += cpu
    g.gpu += gpu
  })
  return result
}

function activity(older, newer) {
  var g = groups(older, newer), total = 0
  for (var k in g) total += g[k].cpu + g[k].gpu
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
  var grouped = groups(oldest, newest), total = 0
  for (var key in grouped) total += grouped[key].cpu + grouped[key].gpu
  var dynamic = activePower(history.power || [], oldest.time)
  var items = Object.keys(grouped).map(function(k) {
    var g = grouped[k]
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

// History: 15-minute buckets, aggregated in memory and flushed when a bucket ends.
var BUCKET = 900
var BUCKET_APPS = 5
var MAX_GAP = 120

function bucketStart(epochSeconds) { return Math.floor(epochSeconds / BUCKET) * BUCKET }

// info: { now: epoch seconds, onBattery, rate (W), level (%) }
function accumulate(pending, older, newer, info) {
  var start = bucketStart(info.now)
  var flushed = null
  if (pending && pending.start !== start) { flushed = finish(pending); pending = null }
  var p = pending ? Object.assign({}, pending, { apps: Object.assign({}, pending.apps) })
    : { start: start, seconds: 0, battery: 0, charged: 0, wh: 0, active: 0, level: null, apps: {} }
  var seconds = older && newer ? newer.time - older.time : 0
  // Suspend or a stalled shell leaves a gap rather than invented values.
  if (seconds > 0 && seconds <= MAX_GAP) {
    p.seconds += seconds
    if (info.onBattery) {
      p.battery += seconds
      if (info.rate > 0) p.wh += info.rate * seconds / 3600
      var g = groups(older, newer)
      for (var key in g) {
        var cores = (g[key].cpu + g[key].gpu) * seconds
        if (!(cores > 0)) continue
        var app = p.apps[key] || { name: g[key].name, kind: g[key].kind, cores: 0 }
        p.apps[key] = { name: app.name, kind: app.kind, cores: app.cores + cores }
        p.active += cores
      }
    } else p.charged += seconds
  }
  if (typeof info.level === "number" && isFinite(info.level)) p.level = Math.max(0, Math.min(100, info.level))
  return { pending: p, flushed: flushed }
}

// The stored form: rounded numbers and only the top apps.
function finish(p) {
  if (!p || p.seconds < 30) return null
  var apps = Object.keys(p.apps).map(function(k) { return p.apps[k] })
  apps.sort(function(a, b) { return b.cores - a.cores || (a.name < b.name ? -1 : 1) })
  function round(value, digits) { var f = Math.pow(10, digits); return Math.round(value * f) / f }
  return { start: p.start, seconds: round(p.seconds, 1), battery: round(p.battery, 1), charged: round(p.charged, 1),
           wh: round(p.wh, 4), active: round(p.active, 2), level: p.level === null ? null : round(p.level, 1),
           apps: apps.slice(0, BUCKET_APPS).map(function(a) { return { name: a.name, kind: a.kind, cores: round(a.cores, 2) } }) }
}

// Stored buckets plus the bucket still being recorded, combined if they share a start.
function withPending(buckets, pending) {
  var current = finish(pending)
  if (!current) return buckets || []
  var result = [], merged = false
  ;(buckets || []).forEach(function(b) {
    if (b.start !== current.start) { result.push(b); return }
    merged = true
    result.push({ start: b.start, seconds: b.seconds + current.seconds, battery: b.battery + current.battery,
                  charged: b.charged + current.charged, wh: b.wh + current.wh, active: b.active + current.active,
                  level: current.level !== null ? current.level : b.level, apps: b.apps.concat(current.apps) })
  })
  if (!merged) result.push(current)
  return result
}

// 96 slots for the last 24 hours, oldest first; missing buckets stay empty.
function daySlots(buckets, now) {
  var byStart = {}
  ;(buckets || []).forEach(function(b) { byStart[b.start] = b })
  var last = bucketStart(now), slots = []
  for (var i = 95; i >= 0; --i) {
    var start = last - i * BUCKET, b = byStart[start]
    slots.push(b ? { start: start, level: b.level, plugged: b.charged > b.battery,
                     watts: b.battery >= 60 ? b.wh * 3600 / b.battery : null } : { start: start, level: null, plugged: false, watts: null })
  }
  return slots
}

// The last 10 local calendar days, oldest first: battery energy used and time on battery.
function weekDays(buckets, now) {
  var days = []
  var today = new Date(now * 1000)
  today.setHours(0, 0, 0, 0)
  for (var i = 9; i >= 0; --i) {
    var day = new Date(today.getTime())
    day.setDate(today.getDate() - i)
    var next = new Date(day.getTime())
    next.setDate(day.getDate() + 1)
    days.push({ start: day.getTime() / 1000, end: next.getTime() / 1000, wh: 0, battery: 0 })
  }
  ;(buckets || []).forEach(function(b) {
    for (var j = 0; j < days.length; ++j) if (b.start >= days[j].start && b.start < days[j].end) {
      days[j].wh += b.wh
      days[j].battery += b.battery
    }
  })
  return days
}

// Share of on-battery activity per app since a time, largest first.
function topApps(buckets, since, limit) {
  var totals = {}, total = 0
  ;(buckets || []).forEach(function(b) {
    if (b.start < since) return
    ;(b.apps || []).forEach(function(a) {
      var key = a.kind + "\n" + a.name
      totals[key] = totals[key] || { name: a.name, kind: a.kind, cores: 0 }
      totals[key].cores += a.cores
    })
    total += b.active || 0
  })
  var items = Object.keys(totals).map(function(k) {
    var t = totals[k]
    return { name: t.name, kind: t.kind, cores: t.cores, share: total > 0 ? t.cores / total : 0 }
  })
  items.sort(function(a, b) { return b.cores - a.cores || (a.name < b.name ? -1 : 1) })
  return items.slice(0, limit || 8)
}

if (typeof module !== "undefined") module.exports = { WINDOW, SIGNIFICANT, LIMIT, MIN_WEIGHT, BUCKET, empty, record, usage, activePower, validModel, learn, fit, groups, activity, laptopPower, bucketStart, accumulate, finish, withPending, daySlots, weekDays, topApps }
