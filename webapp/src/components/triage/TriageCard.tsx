import type { TriageUIState } from "../../../../shared/types"
import { useNextActions } from "../../hooks/useNextActions"

interface TriageCardProps {
  triage: TriageUIState
  emergencyContactPhone: string | null
}

const SEV_CONFIG: Record<string, { label: string; color: string; borderColor: string; bgColor: string; glowColor: string }> = {
  emergent: {
    label: "EMERGENT — ESI 1-2",
    color: "#FF7B93",
    borderColor: "rgba(255,123,147,0.35)",
    bgColor: "rgba(255,123,147,0.08)",
    glowColor: "rgba(255,123,147,0.1)",
  },
  urgent: {
    label: "URGENT — ESI 3",
    color: "#F59E0B",
    borderColor: "rgba(245,158,11,0.35)",
    bgColor: "rgba(245,158,11,0.08)",
    glowColor: "rgba(245,158,11,0.08)",
  },
  moderate: {
    label: "MODERATE — ESI 3",
    color: "#35A7C4",
    borderColor: "rgba(53,167,196,0.35)",
    bgColor: "rgba(53,167,196,0.08)",
    glowColor: "rgba(53,167,196,0.08)",
  },
  routine: {
    label: "NON-URGENT — ESI 4-5",
    color: "#00D2FF",
    borderColor: "rgba(0,210,255,0.35)",
    bgColor: "rgba(0,210,255,0.08)",
    glowColor: "rgba(0,210,255,0.06)",
  },
}

function getMonogram(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("")
}

function getCategoryLabel(category: string): string {
  switch (category) {
    case "hospital": return "Hospital"
    case "ambulatory": return "Walk-in Clinic"
    case "pharmacy": return "Pharmacy"
    default: return "Care Centre"
  }
}

import { useConfig } from "../../hooks/useConfig"

export function TriageCard({ triage, emergencyContactPhone }: TriageCardProps) {
  const config = useConfig()
  const { call911, messageEmergencyContact, getDirections, saveRecommendation } = useNextActions(triage.severity)

  if (!triage.active || !triage.severity) return null

  const sev = SEV_CONFIG[triage.severity] ?? {
    label: triage.severity.toUpperCase(),
    color: "#7AA0B0",
    borderColor: "rgba(130,165,178,0.35)",
    bgColor: "rgba(130,165,178,0.08)",
    glowColor: "rgba(130,165,178,0.06)",
  }

  const allFacilities = triage.recommendedFacility
    ? [triage.recommendedFacility, ...triage.nearbyFacilities]
    : triage.nearbyFacilities

  const recommended =
    allFacilities.find(f => f.id === triage.recommendedFacilityId) ?? triage.recommendedFacility

  const recommendedRoute = triage.routes.find(r => r.facilityId === triage.recommendedFacilityId)

  const otherFacilities = triage.nearbyFacilities.map(f => ({
    facility: f,
    route: triage.routes.find(r => r.facilityId === f.id),
  }))

  const monogram = recommended ? getMonogram(recommended.name) : ""
  const distKm = recommendedRoute?.distanceKm ?? recommended?.distanceKm ?? 0
  const bikeMin = distKm > 0 ? Math.max(2, Math.round((distKm / 12) * 60)) : null
  const walkMin = distKm > 0 ? Math.max(5, Math.round((distKm / 5) * 60)) : null

  return (
    <div
      style={{
        marginTop: 12,
        background: "rgba(10, 29, 39, 0.88)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        border: `1px solid ${sev.borderColor}`,
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: `0 4px 28px ${sev.glowColor}, 0 1px 0 rgba(255,255,255,0.03) inset`,
      }}
    >
      {/* Severity chip header */}
      <div className="flex items-center justify-between px-3.5 py-2.5">
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "3px 10px",
            borderRadius: 99,
            border: `1px solid ${sev.borderColor}`,
            background: sev.bgColor,
            color: sev.color,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          {sev.label}
        </span>
        <span style={{ color: "#7AA0B0", fontSize: 10, fontFamily: "var(--font-mono)" }}>
          Just now
        </span>
      </div>

      <div className="px-3 pb-3 flex flex-col gap-2.5">

        {/* Primary facility card */}
        {recommended && (
          <div
            style={{
              background: "rgba(6, 18, 25, 0.65)",
              border: "1px solid rgba(72, 246, 193, 0.18)",
              borderRadius: 10,
              padding: "11px 12px",
            }}
          >
            {/* Avatar + title */}
            <div className="flex items-start gap-3 mb-2.5">
              <div
                className="flex-none w-10 h-10 rounded-lg flex items-center justify-center text-[13px] font-bold"
                style={{
                  background: "rgba(53,167,196,0.12)",
                  border: "1.5px solid rgba(53,167,196,0.35)",
                  color: "#35A7C4",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.02em",
                  flexShrink: 0,
                }}
              >
                {monogram}
              </div>
              <div className="flex-1 min-w-0">
                <div
                  className="font-bold leading-snug mb-1"
                  style={{ color: "#E2F1F5", fontSize: 13 }}
                >
                  {recommended.name}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      color: "#35A7C4",
                      background: "rgba(53,167,196,0.1)",
                      border: "1px solid rgba(53,167,196,0.22)",
                      borderRadius: 4,
                      padding: "1px 6px",
                    }}
                  >
                    {getCategoryLabel(recommended.category)}
                  </span>
                  <span
                    className="flex items-center gap-1"
                    style={{ fontSize: 10, fontWeight: 700, color: "#48F6C1" }}
                  >
                    <span style={{ fontSize: 7 }}>●</span> OPEN
                  </span>
                </div>
              </div>
            </div>

            {/* Address */}
            <div className="flex items-start gap-1.5 mb-3">
              <svg className="flex-none mt-0.5" width="10" height="10" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 010-5 2.5 2.5 0 010 5z"
                  fill="#35A7C4"
                  opacity="0.7"
                />
              </svg>
              <span
                style={{
                  fontSize: 10.5,
                  color: "#85A4B1",
                  fontFamily: "var(--font-mono)",
                  lineHeight: 1.4,
                }}
              >
                {recommended.address}
              </span>
            </div>

            {/* Transit mode chips */}
            <div
              className="grid gap-1.5 mb-3"
              style={{ gridTemplateColumns: `repeat(${1 + Number(config.modes_enabled.includes("bike")) + Number(config.modes_enabled.includes("walk"))}, minmax(0, 1fr))` }}
            >
              <div
                style={{
                  padding: "6px 4px",
                  borderRadius: 7,
                  background: "rgba(72,246,193,0.09)",
                  border: "1px solid rgba(72,246,193,0.3)",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 12, marginBottom: 2 }}>🚗</div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#48F6C1", fontFamily: "var(--font-mono)" }}>
                  {recommendedRoute
                    ? `${recommendedRoute.etaMinutes} min`
                    : distKm > 0 ? `~${distKm.toFixed(1)} km` : "—"}
                </div>
                {recommendedRoute && (
                  <div style={{ fontSize: 8.5, color: "rgba(72,246,193,0.5)", fontFamily: "var(--font-mono)" }}>
                    {recommendedRoute.distanceKm} km
                  </div>
                )}
              </div>
              {config.modes_enabled.includes("bike") && (
                <div
                  style={{
                    padding: "6px 4px",
                    borderRadius: 7,
                    background: "rgba(0,210,255,0.07)",
                    border: "1px solid rgba(0,210,255,0.22)",
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 12, marginBottom: 2 }}>🚲</div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#00D2FF", fontFamily: "var(--font-mono)" }}>
                    {bikeMin !== null ? `${bikeMin} min` : "—"}
                  </div>
                </div>
              )}
              {config.modes_enabled.includes("walk") && (
                <div
                  style={{
                    padding: "6px 4px",
                    borderRadius: 7,
                    background: "rgba(28,70,89,0.3)",
                    border: "1px solid rgba(28,70,89,0.55)",
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 12, marginBottom: 2 }}>🚶</div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#7AA0B0", fontFamily: "var(--font-mono)" }}>
                    {walkMin !== null ? `${walkMin} min` : "—"}
                  </div>
                </div>
              )}
            </div>

            {/* Directions CTA — all non-emergent severities */}
            {triage.severity !== "emergent" && (
              <button
                onClick={() => getDirections(recommended.name, recommended.lat, recommended.lng)}
                className="w-full flex items-center justify-center gap-2 font-bold transition-all active:scale-[0.98]"
                style={{
                  height: 40,
                  background: "#48F6C1",
                  color: "#061219",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 13,
                  cursor: "pointer",
                  letterSpacing: "0.01em",
                }}
                onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = "#3CE0AD")}
                onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = "#48F6C1")}
              >
                Get Directions
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        )}

        {/* Emergent: 911 CTA + secondary actions */}
        {triage.severity === "emergent" && (
          <div className="flex flex-col gap-2">
            <button
              onClick={call911}
              className="w-full flex items-center justify-center gap-2 font-bold transition-all active:scale-[0.98]"
              style={{
                height: 44,
                background: "rgba(255,123,147,0.12)",
                color: "#FF7B93",
                border: "1px solid rgba(255,123,147,0.45)",
                borderRadius: 8,
                fontSize: 14,
                cursor: "pointer",
                letterSpacing: "0.02em",
              }}
              onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = "rgba(255,123,147,0.2)")}
              onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = "rgba(255,123,147,0.12)")}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 10.8 19.79 19.79 0 01.22 2.18 2 2 0 012.22 0h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.91 7.91a16 16 0 006.09 6.09l1.27-.64a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 15.92l-.08 1z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Call 911 immediately
            </button>
            <div className="grid grid-cols-2 gap-2">
              {emergencyContactPhone && (
                <GhostButton onClick={() => messageEmergencyContact(emergencyContactPhone)} label="Alert contact" />
              )}
              {recommended && (
                <GhostButton
                  onClick={() => getDirections(recommended.name, recommended.lat, recommended.lng)}
                  label="ER directions"
                />
              )}
            </div>
          </div>
        )}

        {/* Urgent: secondary row */}
        {triage.severity === "urgent" && (
          <div className="grid grid-cols-2 gap-2">
            {emergencyContactPhone && (
              <GhostButton onClick={() => messageEmergencyContact(emergencyContactPhone)} label="Alert contact" />
            )}
            <GhostButton onClick={saveRecommendation} label="Save facility" icon={<BookmarkIcon />} />
          </div>
        )}

        {/* Moderate / routine: save only */}
        {(triage.severity === "moderate" || triage.severity === "routine") && (
          <GhostButton onClick={saveRecommendation} label="Save facility" icon={<BookmarkIcon />} fullWidth />
        )}

        {/* Secondary facilities stack */}
        {otherFacilities.length > 0 && (
          <div
            style={{
              border: "1px dashed rgba(28,70,89,0.5)",
              borderRadius: 8,
              padding: "8px 10px",
            }}
          >
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                color: "#7AA0B0",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              Other nearby options
            </div>
            {otherFacilities.map(({ facility, route }) => (
              <div
                key={facility.id ?? facility.name}
                className="flex items-center justify-between"
                style={{
                  padding: "5px 0",
                  borderTop: "0.5px solid rgba(28,70,89,0.3)",
                }}
              >
                <span
                  className="flex-1 min-w-0 truncate"
                  style={{ color: "#85A4B1", fontSize: 11 }}
                >
                  {facility.name}
                </span>
                <div className="flex items-center gap-2 flex-none ml-2">
                  <span style={{ color: "#7AA0B0", fontFamily: "var(--font-mono)", fontSize: 10 }}>
                    {route ? `${route.etaMinutes} min` : `~${facility.distanceKm} km`}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 600,
                      color: "#7AA0B0",
                      background: "rgba(28,70,89,0.3)",
                      padding: "1px 5px",
                      borderRadius: 4,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                    }}
                  >
                    {facility.category === "hospital"
                      ? "Hospital"
                      : facility.category === "ambulatory"
                        ? "Walk-in"
                        : "Care"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Reasoning */}
        {triage.reasoning && (
          <div
            style={{
              fontSize: 10.5,
              color: "#7AA0B0",
              fontStyle: "italic",
              lineHeight: 1.5,
              borderTop: "0.5px solid rgba(28,70,89,0.35)",
              paddingTop: 8,
              fontFamily: "var(--font-mono)",
            }}
          >
            {triage.reasoning}
          </div>
        )}
      </div>
    </div>
  )
}

function GhostButton({
  onClick,
  label,
  icon,
  fullWidth,
}: {
  onClick: () => void
  label: string
  icon?: React.ReactNode
  fullWidth?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center justify-center gap-1.5 font-semibold transition-all active:scale-[0.98] ${fullWidth ? "w-full" : ""}`}
      style={{
        height: 34,
        borderRadius: 7,
        fontSize: 11,
        cursor: "pointer",
        background: "transparent",
        color: "#85A4B1",
        border: "1px solid rgba(28,70,89,0.55)",
      }}
      onMouseEnter={e => {
        ;(e.currentTarget as HTMLElement).style.color = "#E2F1F5"
        ;(e.currentTarget as HTMLElement).style.borderColor = "rgba(28,70,89,0.9)"
      }}
      onMouseLeave={e => {
        ;(e.currentTarget as HTMLElement).style.color = "#85A4B1"
        ;(e.currentTarget as HTMLElement).style.borderColor = "rgba(28,70,89,0.55)"
      }}
    >
      {icon}
      {label}
    </button>
  )
}

function BookmarkIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
      <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2v16z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
