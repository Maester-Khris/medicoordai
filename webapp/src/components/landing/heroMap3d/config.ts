// Calibration knobs, palette and hard-coded overlay data for the 3D hero map.
// Ported from the light prototype (artifacts/hero-3d-map-light). Everything you are likely to tune lives here.

export type LngLat = [number, number]
export type FacilityKind = 'hospital' | 'walkin' | 'residential'

export interface CameraView {
  center: LngLat
  zoom: number
  pitch: number
  bearing: number
}

export interface Facility {
  id: string
  kind: FacilityKind
  dest?: boolean
  lngLat: LngLat
  label: string
}

export const CONFIG = {
  // OpenFreeMap public instance, no key. Free, commercial use allowed, no SLA, attribution required.
  styleUrl: 'https://tiles.openfreemap.org/styles/bright',

  camera: {
    // bearing -16.7 lines the view up with Toronto's street grid; the centre sits south of the towers
    // so the Gardiner, the slips and the lake are in the frame
    desktop: { center: [-79.3795, 43.6446], zoom: 14.9, pitch: 40, bearing: -16.7 } satisfies CameraView,
    mobile: { center: [-79.3793, 43.6462], zoom: 14.2, pitch: 40, bearing: -16.7 } satisfies CameraView,
    // the camera is fitted to the route and pins for the panel's size (boot.ts); never zoom in past this
    maxFitZoom: 15.6,
  },

  buildings: {
    minzoom: 12.5, // the camera is fitted to the panel, so zoom varies; OpenMapTiles has buildings from z13
    opacity: 1,
    roundedCornerDistance: 1.5, // metres; 0 = sharp corners
    verticalGradient: true, // walls darken towards the ground
    // Map-anchored light. On light colours MapLibre can only DARKEN faces away from the light, so the
    // building colours in PALETTE are the ROOF colours and the walls come out darker.
    // position = [radial, azimuth (deg clockwise from north), polar (deg from straight up)]
    light: { anchor: 'map', intensity: 0.13, position: [1.5, 245, 35] },
  },

  // "Dusk" version of the product's Voyager-like map: cooler and about 15 percent dimmer so the light panel sits calmly on the dark page.
  PALETTE: {
    page: '#E4E9EC', // the distance haze dissolves into this
    ground: '#D3D9DD',
    blocks: '#CDD3D8',
    water: '#B7CDD6',
    waterLabel: '#255460',
    waterLabelHalo: '#CADEE4',
    park: '#CBD8CC',
    parkDeep: '#C3D3C4',
    pedestrian: '#DDE2E5',
    roadMinor: '#ECF0F3',
    roadMinorCasing: '#C4CBD1',
    roadCollector: '#EFE9CC',
    roadCollectorCasing: '#D9D0A6',
    roadMajor: '#EBCB8A',
    roadMajorCasing: '#C9A560',
    path: '#CBD2D6',
    rail: '#B7BEC4',
    // roof colours by render_height (metres)
    buildingByHeight: [0, '#E6EAEE', 60, '#DFE4E9', 300, '#D5DBE1'] as Array<number | string>,
    light: '#FFFFFF',
    label: '#3C4249',
    labelHalo: '#E8ECEF',
    areaLabel: '#353F47',
    route: '#087A6D',
    routeCasing: '#FFFFFF',
    hospital: '#E05555',
    walkin: '#3AC9D4',
    residential: '#74C69D',
    mint: '#47F5C0',
    mintInk: '#10312A',
    chrome: '#313A3D',
    chromeHover: '#3F4A4E',
    chromeText: '#F4F6F6',
    chromeTextDim: '#C8D0D2',
    markerLabel: '#262D30',
  },

  // The route is drawn at street level UNDER the 3D buildings; a lighter "ghost" copy on top keeps
  // the hidden stretches traceable.
  route: { width: 6.5, casingWidth: 11.5, glowWidth: 20, glowOpacity: 0.55, ghostWidth: 4, ghostOpacity: 0.6 },

  labels: {
    streetClasses: ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor'],
    streetSpacing: 420,
    poiClasses: ['park', 'attraction', 'stadium', 'museum', 'town_hall', 'monument', 'theatre', 'college', 'aquarium', 'zoo'],
    poiMaxRank: 4,
    hideOnMobile: ['highway-name-minor', 'poi_r1', 'poi_transit'],
  },

  animation: {
    drawMs: 1800,
    holdMs: 7000,
    fadeMs: 500,
    loop: true,
    // optional slow camera sway; 0 = off (default). It redraws the scene every frame.
    drift: { degrees: 0, periodMs: 44000 },
  },

  loadTimeoutMs: 15000, // no map after this long -> static fallback
}

// ---- overlay data: positions are real places; the chip numbers are SAMPLE values ----
export const ROUTE_START: LngLat = [-79.37913, 43.64604]
export const USER = { lngLat: ROUTE_START, label: 'you are here' }

// Each facility type appears once. The destination is the nearest facility that suits the case
// (one needing an emergency room), which is why the closer walk-in clinic is not the target.
export const FACILITIES: Facility[] = [
  { id: 'dest', kind: 'hospital', dest: true, lngLat: [-79.37833, 43.65331], label: 'Emergency Room' },
  { id: 'walkin', kind: 'walkin', lngLat: [-79.3766, 43.6488], label: 'Walk-in Clinic' }, // illustrative position
  { id: 'residential', kind: 'residential', lngLat: [-79.3842, 43.6479], label: 'Residential Care' }, // illustrative position
]

export const CHIP = {
  name: "St. Michael's Hospital",
  reason: 'Nearest emergency room',
  distance: '1.0 km', // sample
  wait: '35 min wait', // sample
}

// Street-centreline waypoints read from the OpenFreeMap tiles: north up Bay St from Union Station,
// east on Queen St, north on Victoria St. Kept short on purpose: the hero panel is about 620 px tall,
// and a longer route forces a zoom at which the map has no 3D buildings.
export const ROUTE: LngLat[] = [
  [-79.37913, 43.64604], // Bay St x Front St W, beside Union Station ("you are here")
  [-79.3797, 43.64733],
  [-79.38027, 43.64866],
  [-79.38079, 43.64992],
  [-79.3813, 43.65117],
  [-79.38174, 43.65189],
  [-79.37926, 43.65242],
  [-79.37807, 43.65268],
  [-79.37833, 43.65331],
]

export const ARIA_LABEL =
  "Sample map of downtown Toronto. A route runs up Bay Street from a 'you are here' point beside Union Station, then along Queen Street to St. Michael's Hospital. The hospital is the nearest emergency room. A closer walk-in clinic and a residential care home are also marked. Distances and wait times are sample values."
