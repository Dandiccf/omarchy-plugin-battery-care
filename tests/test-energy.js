const assert = require('node:assert/strict')
const e = require('../Energy.js')
const unit = (id, name, cpu, extra = {}) => ({ id, name, kind: 'app', cpu, gpuNs: 0, gpuCycles: 0, ...extra })
const sample = (time, units, gpuClock = null) => ({ time, units, gpuClock })

let h = e.record(e.empty(), sample(0, [unit('a', 'Chromium', 0), unit('b', 'kitty', 0)]), null)
assert.equal(e.usage(h).ready, false)
h = e.record(h, sample(2, []), null)
assert.equal(e.usage(h).ready, false, 'needs a minimum sampling span')

// 10 s: Chromium 5 s of CPU across two scopes, kitty 0.2 s (below significance).
h = e.record(e.empty(), sample(0, [unit('a', 'Chromium', 0), unit('a2', 'Chromium', 1e6, { gpuCycles: 10 }), unit('b', 'kitty', 0)], 1000), null)
h = e.record(h, sample(10, [unit('a', 'Chromium', 4e6), unit('a2', 'Chromium', 2e6, { gpuCycles: 510 }), unit('b', 'kitty', 2e5), unit('n', 'New', 1e6)], 2000), null)
let u = e.usage(h)
assert.equal(u.ready, true)
assert.equal(u.watts, false)
assert.deepEqual(u.items.map(i => i.name), ['Chromium', 'New'])
assert.equal(Math.round(u.items[0].impact), 100, 'CPU 50 + GPU 50 (500 of 1000 clock cycles)')
assert.equal(u.items[1].impact, 10, 'units started inside the window count from zero')
assert.equal(u.items[0].watts, null)

// Counter resets (a replaced unit) never produce negative impact.
h = e.record(e.empty(), sample(0, [unit('a', 'A', 9e6)]), null)
h = e.record(h, sample(10, [unit('a', 'A', 1e6)]), null)
assert.deepEqual(e.usage(h).items, [])

// Rolling window keeps one baseline at or before the window start.
h = e.empty()
for (let t = 0; t <= 600; t += 30) h = e.record(h, sample(t, [unit('a', 'A', t * 1e5)]), 10)
assert.equal(h.samples[0].time, 600 - e.WINDOW)
assert.equal(e.usage(h).seconds, e.WINDOW)

// Watts: drain above the lowest recent rate, split by activity share.
h = e.empty()
for (let t = 0; t <= 300; t += 30) h = e.record(h, sample(t, [unit('a', 'A', 0), unit('b', 'B', 0)]), 6)
for (let t = 330; t <= 480; t += 30) h = e.record(h, sample(t, [unit('a', 'A', (t - 300) * 3e5), unit('b', 'B', (t - 300) * 1e5)]), 10)
u = e.usage(h)
assert.equal(u.watts, true)
// Window 300..480: one 6 W and six 10 W readings average 66/7 W; floor 6 W; A has 3/4.
assert.ok(Math.abs(u.items[0].watts - (66 / 7 - 6) * 0.75) < 1e-9, String(u.items[0].watts))
assert.ok(Math.abs(u.items[1].watts - (66 / 7 - 6) * 0.25) < 1e-9)

// AC power or a missing rate restarts the idle baseline.
h = e.record(h, sample(510, [unit('a', 'A', 0)]), null)
assert.deepEqual(h.power, [])
assert.equal(e.activePower([{ time: 0, rate: 5 }, { time: 100, rate: 6 }], 0), null, 'baseline needs five minutes')

// Invalid samples are ignored; older or duplicate timestamps are replaced.
assert.equal(e.record(h, { time: 'x' }, 1), h)
h = e.record(e.empty(), sample(5, []), null)
h = e.record(h, sample(5, [unit('a', 'A', 1)]), null)
assert.equal(h.samples.length, 1)

// Ties sort by name, and the list is capped.
h = e.record(e.empty(), sample(0, []), null)
h = e.record(h, sample(10, 'abcdefg'.split('').map(n => unit(n, n.toUpperCase(), 1e6))), null)
assert.deepEqual(e.usage(h).items.map(i => i.name), ['A', 'B', 'C', 'D', 'E'])
console.log('energy model tests passed')
{
  // Laptop power model: learned on battery only, then predicted from activity.
  const s = (time, cpu) => ({ time, gpuClock: null, units: [{ id: 'a', name: 'A', kind: 'app', cpu, gpuNs: 0, gpuCycles: 0 }] })
  let h = e.empty(), cpu = 0
  // 12 minutes at 30 s: alternating 0.2 and 1.2 busy cores at 6 W and 16 W (base 4 W, 10 W per core).
  for (let t = 0; t <= 720; t += 30) {
    const load = (t / 30) % 2 ? 1.2 : 0.2
    if (t) cpu += load * 30e6
    h = e.record(h, s(t, cpu), 4 + 10 * load)
  }
  const fitted = e.fit(h.model)
  assert.ok(Math.abs(fitted.base - 4) < 0.05 && Math.abs(fitted.perCore - 10) < 0.05, JSON.stringify(fitted))
  assert.equal(e.laptopPower({ ...h, model: null }), null)
  // On AC: no learning, prediction from the recent window (0.5 cores -> 9 W).
  let ac = { ...h, samples: [], power: [] }
  ac = e.record(ac, s(800, 0), null)
  assert.equal(ac.learned, false)
  ac = e.record(ac, s(830, 15e6), null)
  assert.ok(Math.abs(e.laptopPower(ac) - 9) < 0.1, String(e.laptopPower(ac)))
  // Too little data, an AC gap, or a long gap is not learned.
  let short = e.record(e.empty(), s(0, 0), 10)
  short = e.record(short, s(30, 3e6), 10)
  assert.equal(short.learned, true)
  assert.equal(e.fit(short.model), null, 'needs ten minutes on battery')
  const gap = e.record(short, s(400, 5e6), 10)
  assert.equal(gap.learned, false)
  // A stored model is adopted on startup and invalid ones are ignored.
  const stored = e.record(e.empty(), { ...s(0, 0), model: h.model }, null)
  assert.deepEqual(stored.model, h.model)
  assert.equal(e.record(e.empty(), { ...s(0, 0), model: { w: -1, a: 0, p: 0, aa: 0, ap: 0 } }, null).model, null)
  // Flat load falls back to the mean power.
  let flat = e.empty()
  for (let t = 0, c = 0; t <= 720; t += 30, c += 15e6) flat = e.record(flat, s(t, c), 8)
  assert.deepEqual(e.fit(flat.model), { base: 8, perCore: 0 })
  console.log('laptop power model tests passed')
}
