// Test B: the chat path, measured on its own. Every turn spends real LLM quota.
//
//   STEPS       comma-separated concurrent-turn levels (default 1,2,5,10,20,40)
//   STEP_HOLD   how long each level is held (default 2m)
//
// One iteration is one fresh guest: create a session, send one symptom message, read the reply.
// A fresh guest per turn keeps the per-guest rate limit out of the way; the per-IP limit must be
// raised on the API under test (RATE_LIMIT_CHAT_IP), or the test measures the limiter.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import { BASE_URL, guestHeaders, pick, uuid4 } from './lib.js';

const STEPS = (__ENV.STEPS || '1,2,5,10,20,40').split(',').map((s) => Number(s.trim()));
const STEP_HOLD = __ENV.STEP_HOLD || '2m';

const scenarios = new SharedArray('symptom scenarios', () => JSON.parse(open('./scenarios.json')));

const turnDuration = new Trend('chat_turn_duration', true);
const turnBusy = new Rate('chat_turn_busy');           // 429 from our limiter or the provider's quota
const turnFailed = new Rate('chat_turn_failed');       // anything else that is not a 200
const turnsWithRecommendation = new Counter('chat_turns_with_recommendation');

export const options = {
  scenarios: {
    chat: {
      executor: 'ramping-vus',
      startVUs: 0,
      gracefulRampDown: '30s',
      stages: STEPS.flatMap((level) => [
        { target: level, duration: '10s' },
        { target: level, duration: STEP_HOLD },
      ]),
    },
  },
  // Our own targets, stated as assumptions in the spec. Once chat_turn_busy rises, the test is
  // measuring a rate limit (ours or the provider's), not this API.
  thresholds: {
    chat_turn_duration: [{ threshold: 'p(95)<15000', abortOnFail: true, delayAbortEval: STEP_HOLD }],
    chat_turn_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: STEP_HOLD }],
    chat_turn_busy: ['rate<0.05'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const scenario = pick(scenarios);
  const headers = guestHeaders(uuid4());

  const session = http.post(
    `${BASE_URL}/chat/sessions`,
    JSON.stringify({ first_message: scenario.message }),
    { headers, tags: { name: 'chat_session' } },
  );
  if (!check(session, { 'session created': (r) => r.status === 200 })) {
    turnFailed.add(true);
    sleep(1);
    return;
  }

  const turn = http.post(
    `${BASE_URL}/chat/message`,
    JSON.stringify({ session_id: session.json('id'), content: scenario.message, lat: scenario.lat, lng: scenario.lng }),
    { headers, tags: { name: 'chat_message' }, timeout: '90s' },
  );

  turnBusy.add(turn.status === 429);
  turnFailed.add(turn.status !== 200 && turn.status !== 429);
  if (turn.status === 200) {
    turnDuration.add(turn.timings.duration);
    const triage = turn.json('triage');
    if (triage && triage.recommended_facility) {
      turnsWithRecommendation.add(1);
    }
  }
  sleep(1);
}
