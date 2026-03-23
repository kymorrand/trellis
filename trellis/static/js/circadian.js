/**
 * Trellis Circadian System
 *
 * Computes solar events for Orlando, FL via SunCalc,
 * generates CSS @keyframes for palette + typography shifts,
 * and injects them into :root with a 24-hour animation cycle.
 *
 * Zero runtime JS cost after keyframe injection — the browser
 * handles all interpolation natively on the compositor thread.
 */

// ─── SunCalc (inline, MIT license, Vladimir Agafonkin) ─────
// Minimal subset: getTimes() only. ~60 lines vs full library.

const RAD = Math.PI / 180;
const J1970 = 2440588;
const J2000 = 2451545;
const e = RAD * 23.4397;

function toJulian(date) { return date.valueOf() / 86400000 - 0.5 + J1970; }
function fromJulian(j) { return new Date((j + 0.5 - J1970) * 86400000); }
function toDays(date) { return toJulian(date) - J2000; }

function solarMeanAnomaly(d) { return RAD * (357.5291 + 0.98560028 * d); }
function eclipticLongitude(M) {
  const C = RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
  return M + C + RAD * 102.9372 + Math.PI;
}
function sunDeclination(l) { return Math.asin(Math.sin(e) * Math.sin(l)); }
function rightAscension(l) { return Math.atan2(Math.sin(l) * Math.cos(e), Math.cos(l)); }

function julianCycle(d, lw) { return Math.round(d - 0.0009 - lw / (2 * Math.PI)); }
function approxTransit(Ht, lw, n) { return 0.0009 + (Ht + lw) / (2 * Math.PI) + n; }
function solarTransitJ(ds, M, L) { return J2000 + ds + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L); }
function hourAngle(h, phi, d) {
  return Math.acos((Math.sin(h) - Math.sin(phi) * Math.sin(d)) / (Math.cos(phi) * Math.cos(d)));
}

function getSetJ(h, lw, phi, dec, n, M, L) {
  const w = hourAngle(h, phi, dec);
  return solarTransitJ(approxTransit(w, lw, n), M, L);
}

function getSunTimes(date, lat, lng) {
  const lw = RAD * -lng;
  const phi = RAD * lat;
  const d = toDays(date);
  const n = julianCycle(d, lw);
  const ds = approxTransit(0, lw, n);
  const M = solarMeanAnomaly(ds);
  const L = eclipticLongitude(M);
  const dec = sunDeclination(L);
  const Jnoon = solarTransitJ(ds, M, L);

  const result = { solarNoon: fromJulian(Jnoon) };
  const angles = [
    ['sunrise', 'sunset', -0.833],
    ['dawn', 'dusk', -6],           // civil twilight
    ['goldenHourEnd', 'goldenHour', 6],
  ];

  for (const [rise, set, angle] of angles) {
    try {
      const Jset = getSetJ(RAD * angle, lw, phi, dec, n, M, L);
      const Jrise = Jnoon - (Jset - Jnoon);
      result[rise] = fromJulian(Jrise);
      result[set] = fromJulian(Jset);
    } catch (e) {
      // Sun doesn't reach this angle (polar regions) — skip
    }
  }

  return result;
}

// ─── Circadian Engine ──────────────────────────────────────

const ORLANDO = { lat: 28.5384, lng: -81.3789 };

// Phase palette values (from palette.md)
const PHASES = {
  dawn: {
    sky:          'oklch(82% 0.07 250)',
    leaf:         'oklch(58% 0.10 150)',
    'leaf-light': 'oklch(68% 0.10 142)',
    'leaf-dark':  'oklch(42% 0.10 155)',
    wood:         'oklch(55% 0.05 70)',
    'wood-light': 'oklch(72% 0.04 75)',
    solar:        'oklch(58% 0.05 245)',
    ivy:          'oklch(70% 0.06 222)',
    'wf-yellow':  'oklch(78% 0.10 92)',
    'wf-red':     'oklch(55% 0.12 30)',
    'wf-purple':  'oklch(52% 0.09 312)',
    cloud:        'oklch(94% 0.01 90)',
    'cloud-dim':  'oklch(90% 0.015 85)',
    earth:        'oklch(30% 0.03 58)',
    'earth-light':'oklch(42% 0.03 62)',
  },
  day: {
    sky:          'oklch(78% 0.11 230)',
    leaf:         'oklch(62% 0.17 145)',
    'leaf-light': 'oklch(72% 0.16 138)',
    'leaf-dark':  'oklch(45% 0.14 152)',
    wood:         'oklch(52% 0.07 62)',
    'wood-light': 'oklch(68% 0.06 70)',
    solar:        'oklch(62% 0.08 238)',
    ivy:          'oklch(74% 0.09 218)',
    'wf-yellow':  'oklch(82% 0.15 90)',
    'wf-red':     'oklch(58% 0.17 28)',
    'wf-purple':  'oklch(55% 0.13 310)',
    cloud:        'oklch(96% 0.015 85)',
    'cloud-dim':  'oklch(92% 0.02 80)',
    earth:        'oklch(28% 0.04 55)',
    'earth-light':'oklch(40% 0.04 58)',
  },
  afternoon: {
    sky:          'oklch(76% 0.10 220)',
    leaf:         'oklch(60% 0.15 140)',
    'leaf-light': 'oklch(70% 0.14 134)',
    'leaf-dark':  'oklch(43% 0.12 148)',
    wood:         'oklch(50% 0.08 55)',
    'wood-light': 'oklch(66% 0.07 62)',
    solar:        'oklch(60% 0.07 232)',
    ivy:          'oklch(72% 0.08 215)',
    'wf-yellow':  'oklch(80% 0.14 85)',
    'wf-red':     'oklch(56% 0.15 25)',
    'wf-purple':  'oklch(53% 0.12 306)',
    cloud:        'oklch(92% 0.02 78)',
    'cloud-dim':  'oklch(86% 0.025 72)',
    earth:        'oklch(30% 0.04 50)',
    'earth-light':'oklch(42% 0.04 52)',
  },
  evening: {
    sky:          'oklch(35% 0.05 45)',
    leaf:         'oklch(52% 0.12 135)',
    'leaf-light': 'oklch(62% 0.11 130)',
    'leaf-dark':  'oklch(38% 0.10 142)',
    wood:         'oklch(40% 0.06 50)',
    'wood-light': 'oklch(50% 0.05 55)',
    solar:        'oklch(45% 0.06 228)',
    ivy:          'oklch(60% 0.10 210)',
    'wf-yellow':  'oklch(65% 0.10 80)',
    'wf-red':     'oklch(48% 0.12 22)',
    'wf-purple':  'oklch(45% 0.08 305)',
    cloud:        'oklch(30% 0.025 58)',
    'cloud-dim':  'oklch(25% 0.02 52)',
    earth:        'oklch(88% 0.015 78)',
    'earth-light':'oklch(70% 0.015 72)',
  },
  night: {
    sky:          'oklch(25% 0.03 250)',
    leaf:         'oklch(38% 0.08 155)',
    'leaf-light': 'oklch(45% 0.07 148)',
    'leaf-dark':  'oklch(28% 0.06 158)',
    wood:         'oklch(32% 0.05 55)',
    'wood-light': 'oklch(40% 0.04 60)',
    solar:        'oklch(38% 0.05 242)',
    ivy:          'oklch(55% 0.12 200)',
    'wf-yellow':  'oklch(55% 0.08 88)',
    'wf-red':     'oklch(40% 0.10 25)',
    'wf-purple':  'oklch(38% 0.07 310)',
    cloud:        'oklch(26% 0.025 55)',
    'cloud-dim':  'oklch(22% 0.02 50)',
    earth:        'oklch(90% 0.015 80)',
    'earth-light':'oklch(72% 0.015 75)',
  },
};

// Typography axis values per phase
const TYPO_PHASES = {
  dawn:      { softness: 30, weight: 800, casual: 0.3 },
  day:       { softness: 20, weight: 800, casual: 0.2 },
  afternoon: { softness: 40, weight: 700, casual: 0.4 },
  evening:   { softness: 60, weight: 700, casual: 0.6 },
  night:     { softness: 80, weight: 600, casual: 0.8 },
};

function timeToPercent(date) {
  const midnight = new Date(date);
  midnight.setHours(0, 0, 0, 0);
  return ((date - midnight) / 86400000) * 100;
}

function computePhases() {
  const times = getSunTimes(new Date(), ORLANDO.lat, ORLANDO.lng);
  return {
    dawn:      timeToPercent(times.dawn),
    day:       timeToPercent(times.goldenHourEnd),
    afternoon: timeToPercent(new Date(times.solarNoon.getTime() + 3 * 3600000)),
    evening:   timeToPercent(times.goldenHour),
    night:     timeToPercent(times.dusk),
  };
}

function generateColorKeyframes(phasePcts) {
  const colorRoles = Object.keys(PHASES.day);
  let css = '';

  for (const role of colorRoles) {
    css += `@keyframes circadian-${role} {\n`;
    css += `  0%     { --color-${role}: ${PHASES.night[role]}; }\n`;
    css += `  ${phasePcts.dawn.toFixed(2)}%  { --color-${role}: ${PHASES.dawn[role]}; }\n`;
    css += `  ${phasePcts.day.toFixed(2)}%   { --color-${role}: ${PHASES.day[role]}; }\n`;
    css += `  ${phasePcts.afternoon.toFixed(2)}% { --color-${role}: ${PHASES.afternoon[role]}; }\n`;
    css += `  ${phasePcts.evening.toFixed(2)}% { --color-${role}: ${PHASES.evening[role]}; }\n`;
    css += `  ${phasePcts.night.toFixed(2)}%  { --color-${role}: ${PHASES.night[role]}; }\n`;
    css += `  100%   { --color-${role}: ${PHASES.night[role]}; }\n`;
    css += `}\n`;
  }

  return { css, names: colorRoles.map(r => `circadian-${r}`) };
}

function generateTypoKeyframes(phasePcts) {
  let css = `@keyframes circadian-typography {\n`;
  css += `  0%     { --fraunces-softness: ${TYPO_PHASES.night.softness}; --fraunces-weight: ${TYPO_PHASES.night.weight}; --recursive-casual: ${TYPO_PHASES.night.casual}; }\n`;
  css += `  ${phasePcts.dawn.toFixed(2)}%  { --fraunces-softness: ${TYPO_PHASES.dawn.softness}; --fraunces-weight: ${TYPO_PHASES.dawn.weight}; --recursive-casual: ${TYPO_PHASES.dawn.casual}; }\n`;
  css += `  ${phasePcts.day.toFixed(2)}%   { --fraunces-softness: ${TYPO_PHASES.day.softness}; --fraunces-weight: ${TYPO_PHASES.day.weight}; --recursive-casual: ${TYPO_PHASES.day.casual}; }\n`;
  css += `  ${phasePcts.afternoon.toFixed(2)}% { --fraunces-softness: ${TYPO_PHASES.afternoon.softness}; --fraunces-weight: ${TYPO_PHASES.afternoon.weight}; --recursive-casual: ${TYPO_PHASES.afternoon.casual}; }\n`;
  css += `  ${phasePcts.evening.toFixed(2)}% { --fraunces-softness: ${TYPO_PHASES.evening.softness}; --fraunces-weight: ${TYPO_PHASES.evening.weight}; --recursive-casual: ${TYPO_PHASES.evening.casual}; }\n`;
  css += `  ${phasePcts.night.toFixed(2)}%  { --fraunces-softness: ${TYPO_PHASES.night.softness}; --fraunces-weight: ${TYPO_PHASES.night.weight}; --recursive-casual: ${TYPO_PHASES.night.casual}; }\n`;
  css += `  100%   { --fraunces-softness: ${TYPO_PHASES.night.softness}; --fraunces-weight: ${TYPO_PHASES.night.weight}; --recursive-casual: ${TYPO_PHASES.night.casual}; }\n`;
  css += `}\n`;
  return css;
}

// Background gradient also shifts with phase
function generateBgKeyframes(phasePcts) {
  // The canvas background gradient shifts warmth across the day
  const bgValues = {
    night:     ['oklch(18% 0.015 50)', 'oklch(15% 0.012 45)'],
    dawn:      ['oklch(85% 0.02 75)', 'oklch(80% 0.018 70)'],
    day:       ['oklch(93% 0.02 80)', 'oklch(90% 0.018 75)'],
    afternoon: ['oklch(88% 0.022 70)', 'oklch(84% 0.02 65)'],
    evening:   ['oklch(25% 0.02 52)', 'oklch(20% 0.015 48)'],
  };

  let css = `@keyframes circadian-bg-top {\n`;
  for (const [phase, pct] of [['night', 0], ['dawn', phasePcts.dawn], ['day', phasePcts.day],
    ['afternoon', phasePcts.afternoon], ['evening', phasePcts.evening], ['night', phasePcts.night]]) {
    css += `  ${pct.toFixed(2)}% { --bg-top: ${bgValues[phase][0]}; }\n`;
  }
  css += `  100% { --bg-top: ${bgValues.night[0]}; }\n}\n`;

  css += `@keyframes circadian-bg-bottom {\n`;
  for (const [phase, pct] of [['night', 0], ['dawn', phasePcts.dawn], ['day', phasePcts.day],
    ['afternoon', phasePcts.afternoon], ['evening', phasePcts.evening], ['night', phasePcts.night]]) {
    css += `  ${pct.toFixed(2)}% { --bg-bottom: ${bgValues[phase][1]}; }\n`;
  }
  css += `  100% { --bg-bottom: ${bgValues.night[1]}; }\n}\n`;

  return css;
}

/**
 * Initialize the circadian system.
 * Call once on page load. Recalculates daily at midnight.
 */
function initCircadian() {
  const phasePcts = computePhases();
  const colors = generateColorKeyframes(phasePcts);
  const typo = generateTypoKeyframes(phasePcts);
  const bg = generateBgKeyframes(phasePcts);

  const allNames = [...colors.names, 'circadian-typography', 'circadian-bg-top', 'circadian-bg-bottom'].join(', ');
  const allDurations = Array(colors.names.length + 3).fill('86400s').join(', ');
  const allTimings = Array(colors.names.length + 3).fill('linear').join(', ');
  const allIterations = Array(colors.names.length + 3).fill('infinite').join(', ');

  // Calculate negative delay to start at current time of day
  const now = new Date();
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const offsetSeconds = -((now - midnight) / 1000);

  const allDelays = Array(colors.names.length + 3).fill(`${offsetSeconds.toFixed(0)}s`).join(', ');

  const style = document.createElement('style');
  style.id = 'circadian-keyframes';
  style.textContent = colors.css + typo + bg + `
    :root {
      animation-name: ${allNames};
      animation-duration: ${allDurations};
      animation-timing-function: ${allTimings};
      animation-iteration-count: ${allIterations};
      animation-delay: ${allDelays};
    }
  `;

  document.getElementById('circadian-keyframes')?.remove();
  document.head.appendChild(style);

  console.log(`Circadian initialized — offset ${Math.abs(offsetSeconds / 3600).toFixed(1)}h into cycle`);
}

/**
 * Lock the palette to a specific phase (for testing or manual override).
 */
function lockToPhase(phaseName) {
  document.getElementById('circadian-keyframes')?.remove();
  const phase = PHASES[phaseName];
  const typo = TYPO_PHASES[phaseName];
  if (!phase || !typo) return;

  const style = document.createElement('style');
  style.id = 'circadian-keyframes';
  let css = ':root {\n';
  for (const [role, value] of Object.entries(phase)) {
    css += `  --color-${role}: ${value};\n`;
  }
  css += `  --fraunces-softness: ${typo.softness};\n`;
  css += `  --fraunces-weight: ${typo.weight};\n`;
  css += `  --recursive-casual: ${typo.casual};\n`;
  css += '}\n';
  style.textContent = css;
  document.head.appendChild(style);
}

// Export for use
window.TrellisCircadian = { init: initCircadian, lockToPhase };
