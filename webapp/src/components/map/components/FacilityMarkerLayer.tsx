import L from 'leaflet'
import { Marker, Popup } from 'react-leaflet'
import type { MutableRefObject } from 'react'
import type { Facility, FacilityCandidate } from '../../../../../shared/types'
import { getFacilityIcon } from '../config/icons'
import { UnifiedFacilityPopup } from './UnifiedFacilityPopup'
import { useMapContext } from '../context/MapContext'

interface FacilityMarkerLayerProps {
  displayedFacilities: Facility[]
  triageCandidates:    FacilityCandidate[]
  pinnedIdRef:         MutableRefObject<string | null>
  distanceMap?:        Map<string, number>
}

export function FacilityMarkerLayer({ displayedFacilities, triageCandidates, pinnedIdRef, distanceMap }: FacilityMarkerLayerProps) {
  const { activeTriage, recommendedId, isMobile } = useMapContext()

  const facilityHandlers = (id: string) => ({
    mouseover(e: L.LeafletMouseEvent) {
      if (!isMobile) {
        pinnedIdRef.current = null
        e.target.openPopup()
      }
    },
    mouseout(e: L.LeafletMouseEvent) {
      if (!isMobile && pinnedIdRef.current !== id) e.target.closePopup()
    },
    click() {
      pinnedIdRef.current = id
    },
    popupclose() {
      if (pinnedIdRef.current === id) pinnedIdRef.current = null
    },
  })

  if (activeTriage.active) {
    return (
      <>
        {triageCandidates.map(facility => (
          <Marker
            key={facility.id ?? facility.name}
            position={[facility.lat, facility.lng]}
            icon={getFacilityIcon(facility, recommendedId, true)}
            eventHandlers={facilityHandlers(facility.id ?? facility.name)}
          >
            <Popup>
              <UnifiedFacilityPopup
                name={facility.name}
                category={facility.category}
                address={facility.address}
                distanceKm={facility.distanceKm}
              />
            </Popup>
          </Marker>
        ))}
      </>
    )
  }

  return (
    <>
      {displayedFacilities.map(facility => (
        <Marker
          key={facility.id ?? facility.name}
          position={[facility.lat, facility.lng]}
          icon={getFacilityIcon(facility, null, false)}
          eventHandlers={facilityHandlers(facility.id ?? facility.name)}
        >
          <Popup>
            <UnifiedFacilityPopup
              name={facility.name}
              category={facility.category}
              address={facility.address}
              phone={facility.phone}
              weekday_hours={facility.weekday_hours}
              wait_minutes={facility.wait_minutes}
              raw_wait={facility.raw_wait}
              predicted={facility.predicted}
              distanceKm={facility.id ? distanceMap?.get(facility.id) : undefined}
            />
          </Popup>
        </Marker>
      ))}
    </>
  )
}
