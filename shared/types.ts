// ── Chat ────────────────────────────────────────────────────────────────────

export interface Message {
  id:         string
  session_id: string
  user_id:    string
  role:       "user" | "assistant"
  content:    string
  created_at: string
}

export interface Session {
  id:         string
  user_id:    string
  title:      string
  created_at: string
  updated_at: string
}

export interface ConversationsCache {
  sessions: Session[]
  messages: Record<string, Message[]>
}

// ── Triage ───────────────────────────────────────────────────────────────────

export type Severity         = "routine" | "moderate" | "urgent" | "emergent";
export type FacilityCategory = "hospital" | "ambulatory" | "residential";

export interface Facility {
  name:                 string;
  category:             FacilityCategory;
  source_facility_type: string;
  accepted_severity:    Severity[];
  address:              string;
  lat:                  number;
  lng:                  number;
  id?:                  string;
  source?:              string;
  created_at?:          string;
  updated_at?:          string;
  phone?:               string | null;
  business_status?:     string | null;
  weekday_hours?:       string[] | null;
  wait_minutes?:        number | null;
  raw_wait?:            string | null;
  predicted?:           boolean;
}

// ── Proximity ─────────────────────────────────────────────────────────────────

export type AnchorSource = 'gps' | 'manual_pin' | 'default'

export interface UserAnchor {
  lat:    number
  lng:    number
  source: AnchorSource
}

export interface NearbyFacility {
  facility_id:     string
  facility_name:   string
  category:        string
  address:         string
  phone:           string | null
  is_operational:  boolean
  distance_m:      number
  eta_walk_min:    number
  eta_transit_min: number
  eta_drive_min:   number
  wait_minutes:    number | null
}

export interface TriageRequest {
  message: string;
  lat:     number;
  lng:     number;
}

export interface ToolTrace {
  tool:        string;
  status:      "pending" | "done" | "error";
  durationMs?: number;
}

export interface FacilityCandidate {
  id:          string
  name:        string
  category:    FacilityCategory
  address:     string
  lat:         number
  lng:         number
  distanceKm:  number
}

export interface TriageResult {
  severity:             Severity
  reasoning:            string
  recommended_facility: FacilityCandidate | null
  nearby_facilities:    FacilityCandidate[]
}

export interface ChatMessageResponse {
  user_message:      Message
  assistant_message: Message
  triage:            TriageResult | null
}

// ── Profile ────────────────────────────────────────────────────────────────

export interface Profile {
  id:                       string
  user_id:                  string
  getting_started_done:     boolean
  location_preference:      'always' | 'ask'
  push_enabled:              boolean
  emergency_contact_name:   string | null
  emergency_contact_phone:  string | null
  auto_alert_opt_in:        boolean
  allergies:                string | null
  conditions:               string | null
  blood_type:               string | null
  medical_chat_opt_in:      boolean
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface SendNotificationRequest {
  player_id: string
  title: string
  body: string
}

export interface SendNotificationResponse {
  notification_id: string | null
}

export interface NotificationDevice {
  subscription_id: string
  device_type:     string
  active:          boolean
}

export interface ListDevicesResponse {
  devices: NotificationDevice[]
}

// ── Triage UI ─────────────────────────────────────────────────────────────────

export interface RouteResult {
  facilityId:  string
  etaMinutes:  number
  distanceKm:  number
}

export interface TriageUIState {
  active:                boolean
  severity:              Severity | null
  reasoning:             string | null
  recommendedFacility:   FacilityCandidate | null
  nearbyFacilities:      FacilityCandidate[]
  userCoords:            { lat: number; lng: number } | null
  routes:                RouteResult[]
  recommendedFacilityId: string | null
  roadGeometry:          [number, number][] | null
}

// ── Guest demo ────────────────────────────────────────────────────────────────

export type TravelModeKey = "car" | "bike" | "bus" | "walk"

export interface AppConfig {
  demo_mode:         boolean
  starter_prompts:   string[]
  downtown_fallback: { lat: number; lng: number }
  modes_enabled:     TravelModeKey[]
}

export type Thumb = "up" | "down"

export interface FeedbackRequest {
  session_id: string
  message_id: string
  thumb:      Thumb
  comment?:   string | null
}

export interface GuestEventRequest {
  type:         "route_drawn" | "mode_changed"
  session_id:   string
  mode?:        TravelModeKey   // required for mode_changed; sent with route_drawn
  duration_ms?: number          // mode_changed only: click to route redrawn, 0..120000
}

export interface RoutesRequest {
  origin:       { lat: number; lng: number }
  facility_ids: string[]        // 1 to 3, unique
  mode:         TravelModeKey
}

export interface CandidateRoute {
  facility_id: string
  eta_minutes: number | null             // null when this candidate has no route
  distance_km: number | null
  geometry:    [number, number][] | null // [lat, lng] pairs
}

export interface RoutesResponse {
  mode:                TravelModeKey
  routes:              CandidateRoute[]  // same order as facility_ids
  fastest_facility_id: string | null
}

export interface BusyResponse {
  code:        "busy"
  retry_after: number
}
