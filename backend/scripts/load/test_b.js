// Test B: the chat path, measured on its own. Against a real provider every turn spends LLM
// quota; against the mock (GROQ_BASE_URL on the target) it spends none.
//
//   STEPS       comma-separated concurrent-conversation levels
//               (default 40,100,250,500,1000,1500,2000)
//   STEP_HOLD   how long each level is held (default 2m)
//   TURNS_MIN   fewest user turns in a conversation (default 2)
//   TURNS_MAX   most user turns in a conversation (default 3)
//
// One iteration is one fresh guest holding one conversation: create a session with a symptom
// message, then send 1 to 2 more turns, reading each reply. Origins are spread over the city, not
// the handful in scenarios.json. A guest is used once, so the per-guest rate limit stays out of
// the way; the per-IP limit must be raised on the API under test (RATE_LIMIT_CHAT_IP).
//
// A busy answer (429: our admission limit, our rate limiter or the provider's quota) is counted
// apart from a failure, and ends that conversation: the test does not retry.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import { BASE_URL, guestHeaders, pick, randomTorontoPoint, uuid4 } from './lib.js';

const STEPS = (__ENV.STEPS || '40,100,250,500,1000,1500,2000').split(',').map((s) => Number(s.trim()));
const STEP_HOLD = __ENV.STEP_HOLD || '2m';
const TURNS_MIN = Number(__ENV.TURNS_MIN || 2);
const TURNS_MAX = Number(__ENV.TURNS_MAX || 3);

const scenarios = new SharedArray('symptom scenarios', () => JSON.parse(open('./scenarios.json')));
const FOLLOW_UPS = [
  'It started about two days ago and has been getting worse.',
  'I would say it is a six out of ten, and nothing I have tried helps.',
  'No fever or other symptoms that I have noticed.',
  'It is worse when I move and a little better when I rest.',
];

const turnDuration = new Trend('chat_turn_duration', true);
const turnBusy = new Rate('chat_turn_busy');           // 429: admission limit, our limiter, or the provider's quota
const turnFailed = new Rate('chat_turn_failed');       // anything else that is not a 200
const turnsWithRecommendation = new Counter('chat_turns_with_recommendation');
const conversations = new Counter('chat_conversations');

export const options = {
  scenarios: {
    chat: {
      executor: 'ramping-vus',
      startVUs: 0,
      gracefulRampDown: '60s',
      stages: STEPS.flatMap((level) => [
        { target: level, duration: '10s' },
        { target: level, duration: STEP_HOLD },
      ]),
    },
  },
  // Our own targets, stated as assumptions in the spec. Once chat_turn_busy rises, the test is
  // measuring a limit (ours or the provider's), not this API.
  thresholds: {
    chat_turn_duration: [{ threshold: 'p(95)<15000', abortOnFail: true, delayAbortEval: STEP_HOLD }],
    chat_turn_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: STEP_HOLD }],
    chat_turn_busy: ['rate<0.05'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function sendTurn(headers, sessionId, content, origin) {
  const turn = http.post(
    `${BASE_URL}/chat/message`,
    JSON.stringify({ session_id: sessionId, content, lat: origin.lat, lng: origin.lng }),
    { headers, tags: { name: 'chat_message' }, timeout: '90s' },
  );
  const busy = turn.status === 429;
  turnBusy.add(busy);
  turnFailed.add(turn.status !== 200 && !busy);
  if (turn.status === 200) {
    turnDuration.add(turn.timings.duration);
    const triage = turn.json('triage');
    if (triage && triage.recommended_facility) {
      turnsWithRecommendation.add(1);
    }
  }
  return turn.status === 200;
}

export default function () {
  const scenario = pick(scenarios);
  const origin = randomTorontoPoint();
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
  conversations.add(1);

  const sessionId = session.json('id');
  const turns = TURNS_MIN + Math.floor(Math.random() * (TURNS_MAX - TURNS_MIN + 1));
  for (let i = 0; i < turns; i++) {
    const content = i === 0 ? scenario.message : pick(FOLLOW_UPS);
    if (!sendTurn(headers, sessionId, content, origin)) {
      break; // busy or failed: the conversation ends here
    }
    sleep(1); // a person reads the reply before answering
  }
}
