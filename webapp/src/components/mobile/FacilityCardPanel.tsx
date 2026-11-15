// webapp/src/components/mobile/FacilityCardPanel.tsx
import { useState } from 'react'
import { MapPin } from '@phosphor-icons/react'
import type { TravelModeKey, TriageUIState } from '@shared/types'
import { DIRECTIONS_UNAVAILABLE } from '../../lib/directions'
import { TransitModeGrid } from './TransitModeGrid'
import { FeedbackControl } from '../triage/FeedbackControl'

interface FacilityCardPanelProps {
  triage: TriageUIState
  onGetDirections: (name: string, lat: number, lng: number) => boolean
  onModeChange: (mode: TravelModeKey) => void
  feedback: { sessionId: string; messageId: string } | null
}

function monogram(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')
}

function capitalizeAddress(addr: string): string {
  return addr.replace(/\b\w/g, c => c.toUpperCase())
}

const SECONDARY_ETA_COLOR: Record<string, string> = {
  routine:  '#00D2FF',
  moderate: '#00D2FF',
  urgent:   '#F59E0B',
  emergent: '#FF7B93',
}

export function FacilityCardPanel({ triage, onGetDirections, onModeChange, feedback }: FacilityCardPanelProps) {
  const [directionsFailed, setDirectionsFailed] = useState(false)
  const facility = triage.recommendedFacility
  const recommendedRoute = triage.routes.find(r => r.facilityId === triage.recommendedFacilityId)

  if (!triage.active) return null
  if (!facility) {
    return (
      <div data-testid="no-facility" className="rounded-xl p-3 text-[14px]" style={{ background: 'rgba(10,29,39,1)', border: '1px solid rgba(28,70,89,0.40)', color: '#E2F1F5' }}>
        We could not find a facility near you.{triage.severity === 'emergent' ? ' Call 911 or go to the nearest emergency department.' : ''}
      </div>
    )
  }

  const etaColor = SECONDARY_ETA_COLOR[triage.severity ?? 'routine'] ?? '#00D2FF'

  return (
    <div data-testid="result-card" className="rounded-xl" style={{ background: 'rgba(10,29,39,1)', border: '1px solid rgba(28,70,89,0.40)' }}>
      {/* Primary facility card */}
      <div className="px-4 pt-4 pb-3">
        {/* Header row */}
        <div className="flex items-center gap-3">
          {/* Monogram avatar */}
          <div
            className="flex-none flex items-center justify-center rounded-xl"
            style={{
              width: 44, height: 44,
              background: '#132E3C',
              border: '2px solid #35A7C4',
            }}
          >
            <span
              className="font-bold text-[15px]"
              style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}
            >
              {monogram(facility.name)}
            </span>
          </div>

          {/* Name + category */}
          <div className="flex-1 min-w-0">
            <p
              className="font-semibold text-[14px] leading-tight truncate"
              style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}
            >
              {facility.name}
            </p>
            <span
              className="inline-block mt-1 px-2 py-0.5 rounded-full font-mono text-[9px] uppercase tracking-wide"
              style={{
                background: 'rgba(28,70,89,0.50)',
                color: '#85A4B1',
              }}
            >
              {facility.category}
            </span>
          </div>

        </div>

        {/* Address row */}
        <div className="flex items-center gap-1.5 mt-2">
          <MapPin size={12} color="#35A7C4" />
          <span className="font-mono text-[10px]" style={{ color: '#85A4B1' }}>
            {capitalizeAddress(facility.address)}
          </span>
        </div>

        {/* Transit mode grid */}
        <TransitModeGrid
          etaMinutes={recommendedRoute?.etaMinutes ?? null}
          activeMode={triage.travelMode}
          loading={triage.routeLoading}
          onModeChange={onModeChange}
        />

        {recommendedRoute?.estimated && (
          <div
            role="status"
            data-testid="route-estimated"
            style={{
              marginTop: 10,
              padding: "8px 10px",
              borderRadius: 6,
              background: "rgba(245, 158, 11, 0.1)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              color: "#F59E0B",
              fontSize: 11,
              lineHeight: 1.4,
              fontFamily: "var(--font-mono)",
            }}
          >
            Route unavailable right now. The time shown is an estimate. If this is an emergency, call 911.
          </div>
        )}

        {/* CTA button */}
        <button
          onClick={() => setDirectionsFailed(!onGetDirections(facility.name, facility.lat, facility.lng))}
          className="w-full mt-3 flex items-center justify-center gap-2 font-bold text-[14px] active:scale-[0.97] transition-transform border-none cursor-pointer"
          style={{
            height: 48,
            borderRadius: 12,
            background: '#48F6C1',
            color: '#061219',
            fontFamily: 'var(--font-sans)',
          }}
        >
          Get Directions →
        </button>
        {directionsFailed && (
          <p role="status" className="mt-2 text-[12px]" style={{ color: '#F59E0B' }}>{DIRECTIONS_UNAVAILABLE}</p>
        )}
        {feedback && <FeedbackControl sessionId={feedback.sessionId} messageId={feedback.messageId} />}
      </div>

      {/* Secondary facilities */}
      {triage.nearbyFacilities.length > 0 && (
        <>
          <p
            className="font-mono text-[9px] uppercase tracking-widest px-4 pt-3 pb-2"
            style={{ color: '#85A4B1' }}
          >
            OTHER NEARBY OPTIONS
          </p>
          {triage.nearbyFacilities.map(nearby => {
            const nearbyRoute = triage.routes.find(r => r.facilityId === nearby.id)
            return (
              <div
                key={nearby.id}
                className="flex items-center gap-3 px-4"
                style={{
                  height: 52,
                  borderTop: '1px solid rgba(28,70,89,0.30)',
                }}
              >
                {/* Icon */}
                <div
                  className="flex-none flex items-center justify-center rounded-lg font-bold text-[10px]"
                  style={{
                    width: 32, height: 32,
                    background: 'rgba(28,70,89,0.40)',
                    color: '#85A4B1',
                    fontFamily: 'var(--font-sans)',
                  }}
                >
                  {monogram(nearby.name)}
                </div>

                {/* Name + type */}
                <div className="flex-1 min-w-0">
                  <p
                    className="font-medium text-[13px] truncate"
                    style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}
                  >
                    {nearby.name}
                  </p>
                  <p className="font-mono text-[9px]" style={{ color: '#85A4B1' }}>
                    {nearby.category}
                  </p>
                </div>

                {/* ETA + Save */}
                <div className="flex-none flex items-center gap-2">
                  {nearbyRoute && (
                    <span
                      className="font-mono text-[11px] font-bold"
                      style={{ color: etaColor }}
                    >
                      {nearbyRoute.etaMinutes} MIN
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}
