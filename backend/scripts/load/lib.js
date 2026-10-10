// Shared helpers for the k6 load tests. Run through the official image; see README.md here.
//
//   BASE_URL        API under test, no trailing slash (required)
//   INTERNAL_TOKEN  value of DEMO_INTERNAL_TOKEN on that API, so test guests are marked internal

export const BASE_URL = (__ENV.BASE_URL || '').replace(/\/+$/, '');
if (!BASE_URL) {
  throw new Error('BASE_URL is not set');
}

const INTERNAL_TOKEN = __ENV.INTERNAL_TOKEN || '';

// k6 has no crypto.randomUUID; the API only needs a well-formed v4 UUID as a guest id.
export function uuid4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r % 4) + 8).toString(16);
  });
}

export function guestHeaders(guestId) {
  const headers = { 'Content-Type': 'application/json', 'X-Guest-Id': guestId };
  if (INTERNAL_TOKEN) {
    headers['X-Internal'] = INTERNAL_TOKEN;
  }
  return headers;
}

// A point on land inside the area the facility data covers. The band starts north of the
// shoreline on purpose: a point in Lake Ontario makes the routing provider answer 400.
export function randomTorontoPoint() {
  return {
    lat: 43.69 + Math.random() * 0.09,
    lng: -79.52 + Math.random() * 0.26,
  };
}

export function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}
