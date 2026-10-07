import 'leaflet/dist/leaflet.css'
import { useEffect, useState, useRef, useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Tooltip, Popup } from 'react-leaflet'
import { useMapEvents } from 'react-leaflet'
import type { Facility, TriageUIState } from '../../../../shared/types'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import { useConfig } from '../../hooks/useConfig'
import { cnTowerPos, cartoTileUrl, INACTIVE_TRIAGE, buildTriageCandidates } from './config/constants'
import { cnTowerIcon, userIcon, manualPinIcon } from './config/icons'
import { useGeolocation } from '../../hooks/useGeolocation'
import { useAnchor } from '../../hooks/useAnchor'
import { useProximitySearch } from '../../hooks/useProximitySearch'
import { useMap } from 'react-leaflet'
import { type CategoryFilter, FILTER_OPTIONS } from './config/categories'
import { PROXIMITY_OPTIONS } from './config/proximity'
import { MapProvider } from './context/MapContext'
import { MapFitBounds } from './layers/MapFitBounds'
import { MapSizeGuard } from './layers/MapSizeGuard'
import { RoadRouteLayer } from './layers/RoadRouteLayer'
import { FacilityMarkerLayer } from './components/FacilityMarkerLayer'
import { FacilityLegend } from './components/FacilityLegend'
import { isOpen24h, isOpenWeekends, isOpenNow } from '../../utils/hoursUtils'
import { meetsWaitTimeFilter } from '../../utils/waitTimeUtils'

interface MapPanelProps {
  facilities: Facility[]
  facilitiesLoading: boolean
  triage?: TriageUIState
  verticalLegend?: boolean
  sizeVersion?: number
  onClear?: () => void
}

// Short labels for filter chips
const CHIP_LABEL: Record<CategoryFilter, string> = {
  all: 'All',
  hospital: 'Hospital',
  ambulatory: 'Walk-in',
  residential: 'Residential',
}

export function MapPanel({ facilities, facilitiesLoading, triage, verticalLegend = false, sizeVersion = 0, onClear }: MapPanelProps) {
  const config = useConfig()
  const isMobile = useBreakpoint()
  const pinnedIdRef = useRef<string | null>(null)

  const activeTriage = triage ?? INACTIVE_TRIAGE
  const triageCandidates = buildTriageCandidates(activeTriage)
  const recommendedId = activeTriage.recommendedFacilityId

  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all")
  const [travelMode, setTravelMode] = useState<'car' | 'bike' | 'bus'>('car')

  const geo = useGeolocation()

  const [openNow, setOpenNow] = useState(false)
  const [waitTime, setWaitTime] = useState<string>('all')
  const [proximity, setProximity] = useState<string>('all')
  const [open24h, setOpen24h] = useState(false)
  const [openWeekends, setOpenWeekends] = useState(false)

  const { anchor, manualPin, placePin, clearPin } = useAnchor(geo.coords)
  const { results: proximityResults, loading: proximityLoading } = useProximitySearch(anchor, proximity, categoryFilter)

  const distanceMap = useMemo<Map<string, number>>(
    () => new Map(proximityResults.map(r => [r.facility_id, r.distance_m / 1000])),
    [proximityResults],
  )

  const [waitDropdownOpen, setWaitDropdownOpen] = useState(false)
  const [proxDropdownOpen, setProxDropdownOpen] = useState(false)

  const waitRef = useRef<HTMLDivElement>(null)
  const proxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (waitRef.current && !waitRef.current.contains(e.target as Node)) {
        setWaitDropdownOpen(false)
      }
      if (proxRef.current && !proxRef.current.contains(e.target as Node)) {
        setProxDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (activeTriage.active) setCategoryFilter("all")
  }, [activeTriage.active])

  const counts = {
    all: facilities.length,
    hospital: facilities.filter(f => f.category === "hospital").length,
    ambulatory: facilities.filter(f => f.category === "ambulatory").length,
    residential: facilities.filter(f => f.category === "residential").length,
  }

  const displayedFacilities = useMemo(() => {
    // When proximity results have loaded, they are already category-filtered by the DB.
    // When proximity is not active, apply category filter here on the full list.
    const proximityActive = proximity !== 'all' && !proximityLoading && proximityResults.length > 0

    const list = proximityActive
      ? facilities.filter(f => f.id != null && distanceMap.has(f.id))
      : facilities.filter(f => categoryFilter === 'all' || f.category === categoryFilter)

    // Hours and wait-time filters always applied on the frontend (RPC has no hours column,
    // and wait_minutes is already annotated on every facility regardless of proximity mode)
    return list.filter(f => {
      if (openNow      && isOpenNow(f.weekday_hours)      === false) return false
      if (open24h      && isOpen24h(f.weekday_hours)      === false) return false
      if (openWeekends && isOpenWeekends(f.weekday_hours) === false) return false
      if (!meetsWaitTimeFilter(waitTime, f.wait_minutes)) return false
      return true
    })
  }, [facilities, proximity, proximityLoading, proximityResults, distanceMap, categoryFilter, openNow, open24h, openWeekends, waitTime])

  return (
    <div className="relative h-full w-full isolate">
      <MapContainer center={cnTowerPos} zoom={12} scrollWheelZoom={false} zoomControl={!isMobile} className="h-full w-full z-0">
        <MapProvider activeTriage={activeTriage} recommendedId={recommendedId} isMobile={isMobile}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url={cartoTileUrl('rastertiles/voyager')}
            tileSize={512}
            zoomOffset={-1}
            detectRetina={true}
          />
          <MapFitBounds />
          <MapSizeGuard sizeVersion={sizeVersion} />
          <MapClickHandler onMapClick={placePin} />
          <ProximityAnchorView anchor={anchor} proximity={proximity} />
          {manualPin && (
            <Marker position={[manualPin.lat, manualPin.lng]} icon={manualPinIcon}>
              <Tooltip
                direction="top"
                permanent={false}
                className="proximity-pin-tooltip"
              >
                <span style={{ fontSize: 11, fontWeight: 700, color: '#F97316' }}>⊕ Search anchor</span>
                <br />
                <span style={{ fontSize: 10, color: '#6B7280', fontFamily: 'monospace' }}>
                  {manualPin.lat.toFixed(4)}, {manualPin.lng.toFixed(4)}
                </span>
              </Tooltip>
              <Popup>
                <div style={{ textAlign: 'center', padding: '4px 0' }}>
                  <p style={{ fontSize: 12, fontWeight: 600, margin: '0 0 6px', color: '#3D3A35' }}>
                    Search from here
                  </p>
                  <button
                    onClick={clearPin}
                    style={{
                      fontSize: 11,
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: '1px solid #F97316',
                      background: 'transparent',
                      color: '#F97316',
                      cursor: 'pointer',
                    }}
                  >
                    Remove pin
                  </button>
                </div>
              </Popup>
            </Marker>
          )}
          <Marker position={cnTowerPos} icon={cnTowerIcon}>
            <Tooltip className="text-[13px] font-semibold" direction="top">CN Tower Area</Tooltip>
          </Marker>
          <RoadRouteLayer travelMode={travelMode} />
          <FacilityMarkerLayer
            displayedFacilities={displayedFacilities}
            triageCandidates={triageCandidates}
            pinnedIdRef={pinnedIdRef}
            distanceMap={distanceMap}
          />
          {/* User Location marker */}
          {(activeTriage.userCoords || geo.coords) && (
            <Marker position={[activeTriage.userCoords?.lat ?? geo.coords!.lat, activeTriage.userCoords?.lng ?? geo.coords!.lng]} icon={userIcon}>
              <Tooltip className="text-[13px] font-semibold" direction="top">Your Location</Tooltip>
            </Marker>
          )}
          {/* Focus User Location button */}
          <FocusUserButton geo={geo} isMobile={isMobile} />
        </MapProvider>
      </MapContainer>

      {/* Travel mode selector when triage is active */}
      {!isMobile && activeTriage.active && (
        <div style={{
          position: 'absolute',
          top: 12,
          left: 54,
          zIndex: 20,
          background: 'rgba(10, 29, 39, 0.8)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(28, 70, 89, 0.6)',
          borderRadius: 10,
          padding: '3px',
          display: 'flex',
          gap: 3,
          pointerEvents: 'auto'
        }}>
          {(['car', 'bike', 'bus'] as const).filter(mode => config.modes_enabled.includes(mode)).map(mode => {
            const isActive = travelMode === mode
            const icons = { car: 'ti ti-car', bike: 'ti ti-bike', bus: 'ti ti-bus' }
            const labels = { car: 'Drive', bike: 'Cycle', bus: 'Transit' }
            return (
              <button
                key={mode}
                onClick={() => setTravelMode(mode)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '5px 12px',
                  borderRadius: 7,
                  border: 'none',
                  background: isActive ? '#48F6C1' : 'transparent',
                  color: isActive ? '#061219' : '#A0B8C4',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    ; (e.currentTarget as HTMLElement).style.background = 'rgba(72,246,193,0.08)'
                      ; (e.currentTarget as HTMLElement).style.color = '#E2F1F5'
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    ; (e.currentTarget as HTMLElement).style.background = 'transparent'
                      ; (e.currentTarget as HTMLElement).style.color = '#A0B8C4'
                  }
                }}
              >
                <i className={icons[mode]} style={{ fontSize: 13 }} />
                <span>{labels[mode]}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Filter chips — top-left, hidden when triage is active */}
      {!activeTriage.active && (
        <div style={{
          position: 'absolute',
          top: 12,
          left: isMobile ? 12 : 54,
          right: isMobile ? 12 : 'auto',
          zIndex: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          pointerEvents: 'auto',
        }}>
          {/* Category Filter Chips */}
          <div style={{
            display: 'flex',
            gap: 6,
            overflowX: isMobile ? 'auto' : 'visible',
            whiteSpace: 'nowrap',
            paddingBottom: isMobile ? '4px' : 0,
            scrollbarWidth: 'none',
          }}>
            {FILTER_OPTIONS.map(opt => {
              const active = categoryFilter === opt.value
              return (
                <button
                  key={opt.value}
                  onClick={() => setCategoryFilter(opt.value)}
                  style={{
                    padding: '5px 12px',
                    borderRadius: 999,
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: '0.02em',
                    border: `1px solid ${active ? opt.color : 'rgba(28,70,89,0.5)'}`,
                    background: active ? `${opt.color}22` : 'rgba(6,18,25,0.82)',
                    color: active ? opt.color : '#7AA0B0',
                    cursor: 'pointer',
                    backdropFilter: 'blur(12px)',
                    WebkitBackdropFilter: 'blur(12px)',
                    whiteSpace: 'nowrap',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {CHIP_LABEL[opt.value]} ({opt.value === 'all' ? counts.all : counts[opt.value]})
                </button>
              )
            })}
          </div>

          {/* Static/Interactive Sub-filters */}
          <div style={{
            display: 'flex',
            gap: 6,
            alignItems: 'center',
            overflowX: isMobile ? 'auto' : 'visible',
            whiteSpace: 'nowrap',
            scrollbarWidth: 'none',
          }}>
            {/* Open Now toggle */}
            <button
              onClick={() => setOpenNow(!openNow)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.02em',
                border: `1px solid ${openNow ? '#48F6C1' : 'rgba(28,70,89,0.5)'}`,
                background: openNow ? 'rgba(72,246,193,0.15)' : 'rgba(6,18,25,0.82)',
                color: openNow ? '#48F6C1' : '#7AA0B0',
                cursor: 'pointer',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
                transition: 'all 0.15s ease',
              }}
            >
              <i className="ti ti-clock" style={{ fontSize: 12 }} />
              Open Now
            </button>

            {/* Open 24/7 toggle */}
            <button
              onClick={() => setOpen24h(!open24h)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.02em',
                border: `1px solid ${open24h ? '#48F6C1' : 'rgba(28,70,89,0.5)'}`,
                background: open24h ? 'rgba(72,246,193,0.15)' : 'rgba(6,18,25,0.82)',
                color: open24h ? '#48F6C1' : '#7AA0B0',
                cursor: 'pointer',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
                transition: 'all 0.15s ease',
              }}
            >
              <i className="ti ti-sun" style={{ fontSize: 12 }} />
              Open 24/7
            </button>

            {/* Open weekends toggle */}
            <button
              onClick={() => setOpenWeekends(!openWeekends)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.02em',
                border: `1px solid ${openWeekends ? '#48F6C1' : 'rgba(28,70,89,0.5)'}`,
                background: openWeekends ? 'rgba(72,246,193,0.15)' : 'rgba(6,18,25,0.82)',
                color: openWeekends ? '#48F6C1' : '#7AA0B0',
                cursor: 'pointer',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
                transition: 'all 0.15s ease',
              }}
            >
              <i className="ti ti-calendar-week" style={{ fontSize: 12 }} />
              Open weekends
            </button>

            {/* Wait Time Dropdown */}
            <div ref={waitRef} style={{ position: 'relative' }}>
              <button
                onClick={() => setWaitDropdownOpen(!waitDropdownOpen)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '5px 12px',
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.02em',
                  border: `1px solid ${waitTime !== 'all' ? '#48F6C1' : 'rgba(28,70,89,0.5)'}`,
                  background: waitTime !== 'all' ? 'rgba(72,246,193,0.15)' : 'rgba(6,18,25,0.82)',
                  color: waitTime !== 'all' ? '#48F6C1' : '#7AA0B0',
                  cursor: 'pointer',
                  backdropFilter: 'blur(12px)',
                  WebkitBackdropFilter: 'blur(12px)',
                  transition: 'all 0.15s ease',
                }}
              >
                <i className="ti ti-hourglass-high" style={{ fontSize: 12 }} />
                {waitTime === 'all' ? 'Wait Time: All' : `Wait: ${waitTime}`}
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ transform: waitDropdownOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease', display: 'inline-block', verticalAlign: 'middle', marginLeft: 2 }}>
                  <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>

              {waitDropdownOpen && (
                <div style={{
                  position: 'absolute',
                  top: 'calc(100% + 6px)',
                  left: 0,
                  zIndex: 30,
                  background: 'rgba(6, 18, 25, 0.95)',
                  backdropFilter: 'blur(12px)',
                  WebkitBackdropFilter: 'blur(12px)',
                  border: '1px solid rgba(28, 70, 89, 0.6)',
                  borderRadius: 8,
                  padding: '4px 0',
                  minWidth: 140,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                }}>
                  {[
                    { value: 'all', label: 'All wait times' },
                    { value: '> 10 min', label: '> 10 min' },
                    { value: '> 25 min', label: '> 25 min' },
                    { value: '30 min+', label: '30 min+' },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => {
                        setWaitTime(opt.value)
                        setWaitDropdownOpen(false)
                      }}
                      style={{
                        width: '100%',
                        padding: '7px 14px',
                        background: 'none',
                        border: 'none',
                        textAlign: 'left',
                        fontSize: 11,
                        fontWeight: 600,
                        color: waitTime === opt.value ? '#48F6C1' : '#A0B8C4',
                        cursor: 'pointer',
                        display: 'block',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(28, 70, 89, 0.3)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'none'}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Proximity Dropdown */}
            <div ref={proxRef} style={{ position: 'relative' }}>
              <button
                onClick={() => setProxDropdownOpen(!proxDropdownOpen)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '5px 12px',
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.02em',
                  border: `1px solid ${proximity !== 'all' ? '#48F6C1' : 'rgba(28,70,89,0.5)'}`,
                  background: proximity !== 'all' ? 'rgba(72,246,193,0.15)' : 'rgba(6,18,25,0.82)',
                  color: proximity !== 'all' ? '#48F6C1' : '#7AA0B0',
                  cursor: 'pointer',
                  backdropFilter: 'blur(12px)',
                  WebkitBackdropFilter: 'blur(12px)',
                  transition: 'all 0.15s ease',
                }}
              >
                <i className="ti ti-map-pin" style={{ fontSize: 12 }} />
                {proximityLoading
                  ? 'Searching…'
                  : proximity === 'all'
                    ? 'Proximity: All'
                    : `Dist: ${proximity}`}
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ transform: proxDropdownOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease', display: 'inline-block', verticalAlign: 'middle', marginLeft: 2 }}>
                  <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>

              {proxDropdownOpen && (
                <div style={{
                  position: 'absolute',
                  top: 'calc(100% + 6px)',
                  left: 0,
                  zIndex: 30,
                  background: 'rgba(6, 18, 25, 0.95)',
                  backdropFilter: 'blur(12px)',
                  WebkitBackdropFilter: 'blur(12px)',
                  border: '1px solid rgba(28, 70, 89, 0.6)',
                  borderRadius: 8,
                  padding: '4px 0',
                  minWidth: 140,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                }}>
                  {[
                    { value: 'all', label: 'All distances' },
                    ...PROXIMITY_OPTIONS,
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => {
                        setProximity(opt.value)
                        setProxDropdownOpen(false)
                      }}
                      style={{
                        width: '100%',
                        padding: '7px 14px',
                        background: 'none',
                        border: 'none',
                        textAlign: 'left',
                        fontSize: 11,
                        fontWeight: 600,
                        color: proximity === opt.value ? '#48F6C1' : '#A0B8C4',
                        cursor: 'pointer',
                        display: 'block',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(28, 70, 89, 0.3)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'none'}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Loading indicator */}
      {facilitiesLoading && (
        <div style={{
          position: 'absolute', top: 52, left: 12, zIndex: 15,
          background: 'rgba(6, 18, 25, 0.85)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(28, 70, 89, 0.6)',
          borderRadius: 8, padding: '6px 10px', fontSize: 12, color: '#7AA0B0',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{ width: 12, height: 12, borderRadius: '50%', border: '2px solid #48F6C1', borderTopColor: 'transparent', display: 'inline-block', animation: 'spin 0.8s linear infinite' }} />
          Loading facilities…
        </div>
      )}

      {/* Top-right: clear + facilities badge */}
      <div style={{ position: 'absolute', top: 12, right: 12, zIndex: 20, display: 'flex', alignItems: 'center', gap: 8, pointerEvents: 'auto' }}>
        {onClear && activeTriage.active && (
          <button
            onClick={onClear}
            aria-label="Clear map"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 12px',
              fontSize: 11, fontWeight: 700,
              background: 'rgba(255, 123, 147, 0.15)',
              border: '1px solid rgba(255, 123, 147, 0.50)',
              borderRadius: 999,
              color: '#FF7B93',
              cursor: 'pointer',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              ; (e.currentTarget as HTMLElement).style.background = 'rgba(255, 123, 147, 0.28)'
                ; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255, 123, 147, 0.80)'
            }}
            onMouseLeave={e => {
              ; (e.currentTarget as HTMLElement).style.background = 'rgba(255, 123, 147, 0.15)'
                ; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255, 123, 147, 0.50)'
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
            Clear map
          </button>
        )}
        {!isMobile && (
          <div style={{
            background: 'rgba(6, 18, 25, 0.85)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: '1px solid rgba(28, 70, 89, 0.6)',
            borderRadius: 999,
            padding: '6px 14px',
            fontSize: 11, fontWeight: 700,
            color: '#7AA0B0',
            display: 'flex', alignItems: 'center', gap: 8,
            pointerEvents: 'none',
          }}>
            <span style={{ position: 'relative', display: 'inline-flex', width: 8, height: 8 }}>
              <span
                className="animate-ping absolute inline-flex h-full w-full rounded-full"
                style={{ background: '#48F6C1', opacity: 0.75 }}
              />
              <span style={{ position: 'relative', width: 8, height: 8, borderRadius: '50%', background: '#48F6C1' }} />
            </span>
            {activeTriage.active
              ? `${triageCandidates.length} FACILITIES SHOWN`
              : categoryFilter === 'all'
                ? `${facilitiesLoading ? '—' : facilities.length} FACILITIES ACTIVE`
                : `${displayedFacilities.length} OF ${facilities.length} SHOWN`
            }
          </div>
        )}
      </div>

      <FacilityLegend verticalLegend={verticalLegend} />
    </div>
  )
}

function MapClickHandler({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
  useMapEvents({
    click: (e) => onMapClick(e.latlng.lat, e.latlng.lng),
  })
  return null
}

function ProximityAnchorView({
  anchor,
  proximity,
}: {
  anchor:    { lat: number; lng: number; source: string }
  proximity: string
}) {
  const map = useMap()

  useEffect(() => {
    if (proximity === 'all') return
    // Zoom level: 13 for tight radius (10km), 11 for wide (25/50km)
    const zoom = proximity === '10 km' ? 13 : 11
    map.setView([anchor.lat, anchor.lng], zoom, { animate: true, duration: 0.8 })
  // Re-center whenever anchor coords OR the selected radius changes.
  // anchor.source is intentionally NOT in the deps: we only re-center
  // when the user actively changes radius or moves the anchor point.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor.lat, anchor.lng, proximity])

  return null
}

function FocusUserButton({
  geo,
  isMobile,
}: {
  geo: ReturnType<typeof useGeolocation>
  isMobile: boolean
}) {
  const map = useMap()

  const handleFocus = async () => {
    const coords = await geo.requestOnce()
    if (coords) {
      map.setView([coords.lat, coords.lng], 15, { animate: true })
    }
  }

  return (
    <button
      onClick={handleFocus}
      title="Focus on my location"
      style={{
        position: 'absolute',
        bottom: isMobile ? 236 : 16,
        right: 16,
        zIndex: 1000,
        width: 38,
        height: 38,
        borderRadius: '50%',
        background: 'rgba(6, 18, 25, 0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(28, 70, 89, 0.6)',
        color: '#48F6C1',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
        transition: 'all 0.2s ease',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'rgba(6, 18, 25, 0.95)'
        e.currentTarget.style.borderColor = '#48F6C1'
        e.currentTarget.style.transform = 'scale(1.05)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'rgba(6, 18, 25, 0.85)'
        e.currentTarget.style.borderColor = 'rgba(28, 70, 89, 0.6)'
        e.currentTarget.style.transform = 'scale(1)'
      }}
    >
      {geo.requesting ? (
        <span style={{
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: '2px solid #48F6C1',
          borderTopColor: 'transparent',
          animation: 'spin 0.8s linear infinite',
          display: 'inline-block',
        }} />
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="3" fill="currentColor" />
          <line x1="12" y1="1" x2="12" y2="3" />
          <line x1="12" y1="21" x2="12" y2="23" />
          <line x1="1" y1="12" x2="3" y2="12" />
          <line x1="21" y1="12" x2="23" y2="12" />
        </svg>
      )}
    </button>
  )
}
