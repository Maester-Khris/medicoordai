// Test A: non-LLM capacity. No chat traffic, so it spends no LLM quota.
//
//   SCENARIO   smoke | average | breakpoint | soak   (default smoke)
//   AVG_RATE   requests per second for average and soak (default 10)
//   RATES      breakpoint steps in requests per second (default 10,25,50,100,150,200);
//              each step is a 15 s ramp plus a 2 minute hold
//
// Two streams run side by side:
//   mix     GET /facilities, /facilities/nearby, /config, /health, by weight
//   routes  POST /routes at a low fixed rate. Each call makes three calls on the metered Geoapify
//           key, so it is capped at 2 per second in every scenario and never ramps.
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, guestHeaders, pick, randomTorontoPoint, uuid4 } from './lib.js';

const SCENARIO = __ENV.SCENARIO || 'smoke';
const AVG_RATE = Number(__ENV.AVG_RATE || 10);
const RATES = (__ENV.RATES || '10,25,50,100,150,200').split(',').map((r) => Number(r.trim()));
const STEP_SECONDS = 135;

const ROUTES_PER_SECOND = { smoke: 0.2, average: 1, breakpoint: 2, soak: 0.5 };

// Arrival rate, not looping users: a slow server must not slow the generator down and hide the tail.
const MIX = {
  smoke: { executor: 'constant-arrival-rate', rate: 2, timeUnit: '1s', duration: '1m', preAllocatedVUs: 5, maxVUs: 20 },
  average: {
    executor: 'ramping-arrival-rate', startRate: 1, timeUnit: '1s', preAllocatedVUs: 50, maxVUs: 200,
    stages: [
      { target: AVG_RATE, duration: '1m' },
      { target: AVG_RATE, duration: '5m' },
      { target: 0, duration: '30s' },
    ],
  },
  breakpoint: {
    executor: 'ramping-arrival-rate', startRate: RATES[0], timeUnit: '1s', preAllocatedVUs: 200, maxVUs: 2000,
    stages: RATES.flatMap((rate) => [
      { target: rate, duration: '15s' },
      { target: rate, duration: '2m' },
    ]),
  },
  soak: { executor: 'constant-arrival-rate', rate: AVG_RATE, timeUnit: '1s', duration: '1h', preAllocatedVUs: 50, maxVUs: 200 },
};

if (!MIX[SCENARIO]) {
  throw new Error(`unknown SCENARIO "${SCENARIO}"`);
}

const routesRate = ROUTES_PER_SECOND[SCENARIO];

export const options = {
  scenarios: {
    mix: { ...MIX[SCENARIO], exec: 'mix' },
    routes: {
      executor: 'constant-arrival-rate',
      // k6 wants whole numbers: 0.2 per second is 1 every 5 seconds.
      rate: routesRate >= 1 ? routesRate : 1,
      timeUnit: routesRate >= 1 ? '1s' : `${Math.round(1 / routesRate)}s`,
      duration: SCENARIO === 'smoke' ? '1m' : SCENARIO === 'soak' ? '1h' : SCENARIO === 'average' ? '6m30s' : `${RATES.length * STEP_SECONDS}s`,
      preAllocatedVUs: 10,
      maxVUs: 40,
      exec: 'routes',
    },
  },
  // Our own targets, stated as assumptions in the spec; not an industry standard.
  thresholds: {
    'http_req_failed{scenario:mix}': [{ threshold: 'rate<0.01', abortOnFail: SCENARIO === 'breakpoint', delayAbortEval: '2m' }],
    'http_req_duration{scenario:mix}': [
      { threshold: 'p(95)<500', abortOnFail: SCENARIO === 'breakpoint', delayAbortEval: '2m' },
      'p(99)<1000',
    ],
    'http_req_failed{scenario:routes}': ['rate<0.05'],
    'http_req_duration{scenario:routes}': ['p(95)<5000'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// Browsers ask for compressed responses; without this the facility list travels at 127 KB instead
// of 22 KB and the test measures the network link before the API.
const GZIP = { 'Accept-Encoding': 'gzip' };
const CATEGORIES = [null, 'hospital', 'ambulatory', 'residential'];
const RADII = [5000, 10000, 25000, 50000];
const MODES = ['car', 'bike', 'walk']; // no transit: slowest and the costliest on the provider

export function setup() {
  const res = http.get(`${BASE_URL}/facilities?category=hospital`, { tags: { name: 'setup' } });
  if (res.status !== 200) {
    throw new Error(`setup: GET /facilities answered ${res.status}`);
  }
  const hospitalIds = res.json().map((f) => f.id);
  if (hospitalIds.length < 3) {
    throw new Error('setup: fewer than 3 hospitals returned');
  }
  return { hospitalIds };
}

export function mix() {
  const roll = Math.random() * 100;
  let res;
  if (roll < 42) {
    res = http.get(`${BASE_URL}/facilities`, { headers: GZIP, tags: { name: 'facilities' } });
  } else if (roll < 74) {
    const point = randomTorontoPoint();
    const category = pick(CATEGORIES);
    const query = `lat=${point.lat}&lng=${point.lng}&radius_m=${pick(RADII)}` + (category ? `&category=${category}` : '');
    res = http.get(`${BASE_URL}/facilities/nearby?${query}`, { headers: GZIP, tags: { name: 'nearby' } });
  } else if (roll < 90) {
    res = http.get(`${BASE_URL}/config`, { tags: { name: 'config' } });
  } else {
    res = http.get(`${BASE_URL}/health`, { tags: { name: 'health' } });
  }
  check(res, { 'status is 200': (r) => r.status === 200 });
}

export function routes(data) {
  const ids = [];
  while (ids.length < 3) {
    const id = pick(data.hospitalIds);
    if (!ids.includes(id)) {
      ids.push(id);
    }
  }
  const body = JSON.stringify({ origin: randomTorontoPoint(), facility_ids: ids, mode: pick(MODES) });
  const res = http.post(`${BASE_URL}/routes`, body, { headers: guestHeaders(uuid4()), tags: { name: 'routes' } });
  check(res, { 'routes answered 200': (r) => r.status === 200 });
}
