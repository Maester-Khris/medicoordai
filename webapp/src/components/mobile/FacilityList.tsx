import { memo, useEffect, useMemo, useRef, useState } from 'react'
import type { Facility } from '@shared/types'
import { CATEGORY_STYLES, DEFAULT_STYLE } from '../map/config/categories'
import { DIRECTIONS_UNAVAILABLE } from '../../lib/directions'
import { sortByDistance, type LatLng } from '../../lib/distance'

export const PAGE_SIZE = 8
const ROW_H = 56

interface FacilityListProps {
  facilities: Facility[]
  loading: boolean
  origin: LatLng
  originIsFallback: boolean
  onShowOnMap: (facilityId: string) => void
  onDirections: (name: string, lat: number, lng: number) => boolean
}

interface RowProps {
  facility: Facility
  km: number
  expanded: boolean
  onToggle: (key: string) => void
  onShowOnMap: (facilityId: string) => void
  onDirections: (name: string, lat: number, lng: number) => boolean
}

const keyOf = (f: Facility) => f.id ?? f.name

const Row = memo(function Row({ facility, km, expanded, onToggle, onShowOnMap, onDirections }: RowProps) {
  const [directionsFailed, setDirectionsFailed] = useState(false)
  const rowRef = useRef<HTMLLIElement>(null)
  // Keep the Directions and Show on map buttons in view in the short half-height sheet.
  useEffect(() => {
    if (expanded) rowRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [expanded])
  const style = CATEGORY_STYLES[facility.category] ?? DEFAULT_STYLE
  const wait = facility.wait_minutes != null ? `~${facility.wait_minutes} min wait` : null
  return (
    <li ref={rowRef} data-testid="facility-row" style={{ borderTop: '1px solid rgba(28,70,89,0.30)', contentVisibility: 'auto', containIntrinsicSize: `auto ${ROW_H}px` }}>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => onToggle(keyOf(facility))}
        className="w-full flex items-center gap-3 text-left"
        style={{ minHeight: ROW_H, background: 'none', border: 'none', cursor: 'pointer', color: '#E2F1F5' }}
      >
        <span
          aria-hidden="true"
          className="flex-none flex items-center justify-center rounded-lg font-bold text-[12px]"
          style={{ width: 32, height: 32, background: style.color, color: '#061219' }}
        >
          {style.letter}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-[14px] font-medium truncate">{facility.name}</span>
          <span className="block text-[12px]" style={{ color: '#85A4B1' }}>{style.label}</span>
        </span>
        <span className="flex-none text-right text-[12px]" style={{ color: '#85A4B1' }}>
          <span className="block font-bold" style={{ color: '#E2F1F5' }}>{Number.isFinite(km) ? `${km.toFixed(1)} km` : ''}</span>
          {wait && <span className="block">{wait}</span>}
        </span>
      </button>
      {expanded && (
        <div className="pb-3 flex flex-col gap-2">
          <p className="text-[12px]" style={{ color: '#85A4B1' }}>{facility.address}</p>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="facility-directions"
              onClick={() => setDirectionsFailed(!onDirections(facility.name, facility.lat, facility.lng))}
              className="flex-1 font-bold text-[14px] rounded-xl"
              style={{ minHeight: 44, background: '#48F6C1', color: '#061219', border: 'none', cursor: 'pointer' }}
            >
              Get Directions
            </button>
            <button
              type="button"
              data-testid="facility-show-on-map"
              onClick={() => facility.id && onShowOnMap(facility.id)}
              className="flex-1 font-semibold text-[14px] rounded-xl"
              style={{ minHeight: 44, background: 'transparent', color: '#48F6C1', border: '1px solid #48F6C1', cursor: 'pointer' }}
            >
              Show on map
            </button>
          </div>
          {directionsFailed && <p role="status" className="text-[12px]" style={{ color: '#F59E0B' }}>{DIRECTIONS_UNAVAILABLE}</p>}
        </div>
      )}
    </li>
  )
})

export function FacilityList({ facilities, loading, origin, originIsFallback, onShowOnMap, onDirections }: FacilityListProps) {
  const [count, setCount] = useState(PAGE_SIZE)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const sentinelRef = useRef<HTMLLIElement>(null)

  // Sort once per list or origin (rounded so a jittering GPS fix does not re-sort every render).
  const lat = Math.round(origin.lat * 1000) / 1000
  const lng = Math.round(origin.lng * 1000) / 1000
  const sorted = useMemo(() => sortByDistance(facilities, { lat, lng }), [facilities, lat, lng])

  useEffect(() => { setCount(PAGE_SIZE) }, [lat, lng])

  const hasMore = count < sorted.length
  useEffect(() => {
    const el = sentinelRef.current
    if (!hasMore || !el) return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) setCount(c => c + PAGE_SIZE)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, count])

  const toggle = useMemo(() => (key: string) => setExpandedKey(prev => (prev === key ? null : key)), [])

  if (loading && facilities.length === 0) return <p className="text-[14px]" style={{ color: '#85A4B1' }}>Loading facilities...</p>
  if (facilities.length === 0) return <p className="text-[14px]" style={{ color: '#85A4B1' }}>No facilities found.</p>

  return (
    <div>
      {originIsFallback && <p className="text-[12px] mb-1" style={{ color: '#85A4B1' }}>Distances from downtown Toronto</p>}
      <ul>
        {sorted.slice(0, count).map(({ item, km }) => (
          <Row
            key={keyOf(item)}
            facility={item}
            km={km}
            expanded={expandedKey === keyOf(item)}
            onToggle={toggle}
            onShowOnMap={onShowOnMap}
            onDirections={onDirections}
          />
        ))}
        {hasMore && <li ref={sentinelRef} data-testid="facility-sentinel" aria-hidden="true" style={{ height: 1 }} />}
      </ul>
    </div>
  )
}
