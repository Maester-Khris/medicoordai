from typing import Literal
from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator

class Severity(str, Enum):
    routine  = "routine"
    moderate = "moderate"
    urgent   = "urgent"
    emergent = "emergent"


class FacilityCategory(str, Enum):
    hospital    = "hospital"
    ambulatory  = "ambulatory"
    residential = "residential"


class Facility(BaseModel):
    name:                 str
    category:             FacilityCategory
    source_facility_type: str
    accepted_severity:    list[Severity]
    address:              str
    lat:                  float
    lng:                  float
    id:                   UUID | None = None
    source:               str | None = None
    created_at:           datetime | None = None
    updated_at:           datetime | None = None
    phone:                str | None = None
    business_status:      str | None = None
    weekday_hours:        list[str] | None = None
    wait_minutes:         int | None = None
    raw_wait:             str | None = None
    predicted:            bool = False


class SessionBase(BaseModel):
    id:         UUID
    user_id:    UUID
    title:      str
    created_at: datetime
    updated_at: datetime


class MessageBase(BaseModel):
    id:         UUID
    session_id: UUID
    user_id:    UUID
    role:       str
    content:    str
    created_at: datetime


class SendMessageRequest(BaseModel):
    session_id: UUID
    content:    str = Field(..., min_length=1, max_length=4000)
    lat:        float | None = None
    lng:        float | None = None


class FacilityCandidate(BaseModel):
    id:          str
    name:        str
    category:    FacilityCategory
    address:     str
    lat:         float
    lng:         float
    distanceKm:  float


class TriageResult(BaseModel):
    severity:             Severity
    reasoning:            str
    recommended_facility: FacilityCandidate | None = None
    nearby_facilities:    list[FacilityCandidate] = []


class CreateSessionRequest(BaseModel):
    first_message: str = Field(..., min_length=1, max_length=4000)


class SessionWithMessages(BaseModel):
    session:  SessionBase
    messages: list[MessageBase]


class PastConversationsResponse(BaseModel):
    sessions: list[SessionWithMessages]
    etag:     str


class NearbyFacilityResult(BaseModel):
    facility_id:     str
    facility_name:   str
    category:        str
    address:         str
    phone:           str | None
    is_operational:  bool
    distance_m:      int
    eta_walk_min:    int
    eta_transit_min: int
    eta_drive_min:   int
    wait_minutes:    int | None = None


class Profile(BaseModel):
    id:                      UUID
    user_id:                 UUID
    getting_started_done:    bool
    location_preference:     str
    push_enabled:             bool
    emergency_contact_name:  str | None = None
    emergency_contact_phone: str | None = None
    auto_alert_opt_in:       bool
    allergies:               str | None = None
    conditions:              str | None = None
    blood_type:              str | None = None
    medical_chat_opt_in:     bool


TravelMode = Literal["car", "bike", "bus", "walk"]

class LatLng(BaseModel):
    lat: float
    lng: float


class AppConfig(BaseModel):
    demo_mode:         bool
    starter_prompts:   list[str]
    downtown_fallback: LatLng
    modes_enabled:     list[Literal["car", "bike", "bus", "walk"]]


class FeedbackRequest(BaseModel):
    session_id: UUID
    message_id: UUID
    thumb:      Literal["up", "down"]
    comment:    str | None = Field(default=None, max_length=2000)


class GuestEventRequest(BaseModel):
    type:        Literal["route_drawn", "mode_changed"]
    session_id:  UUID
    mode:        TravelMode | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=120000)

    @model_validator(mode="after")
    def _fields_match_the_type(self) -> "GuestEventRequest":
        if self.type == "mode_changed" and self.mode is None:
            raise ValueError("mode is required for mode_changed")
        if self.type != "mode_changed" and self.duration_ms is not None:
            raise ValueError("duration_ms is only allowed for mode_changed")
        return self


class RoutesRequest(BaseModel):
    origin:       LatLng
    facility_ids: list[str] = Field(..., min_length=1, max_length=3)
    mode:         TravelMode

    @field_validator("origin")
    @classmethod
    def _origin_in_range(cls, origin: LatLng) -> LatLng:
        if not (-90 <= origin.lat <= 90 and -180 <= origin.lng <= 180):
            raise ValueError("origin is out of range")
        return origin

    @field_validator("facility_ids")
    @classmethod
    def _ids_are_unique(cls, ids: list[str]) -> list[str]:
        if len(set(ids)) != len(ids):
            raise ValueError("facility_ids must be unique")
        return ids


class CandidateRoute(BaseModel):
    facility_id: str
    eta_minutes: int | None = None
    distance_km: float | None = None
    geometry:    list[tuple[float, float]] | None = None


class RoutesResponse(BaseModel):
    mode:                TravelMode
    routes:              list[CandidateRoute]
    fastest_facility_id: str | None = None
