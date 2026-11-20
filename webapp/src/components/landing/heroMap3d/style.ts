import type { StyleSpecification } from 'maplibre-gl'
import { CONFIG } from './config'
import { routeGeoJson } from './route'

// OpenFreeMap's style JSON is handled structurally here (layers are retinted by id), so it gets
// small local types instead of MapLibre's strict per-layer-type specs.
interface RawLayer {
  id: string
  type: string
  source?: string
  'source-layer'?: string
  minzoom?: number
  filter?: unknown
  layout?: Record<string, unknown>
  paint?: Record<string, unknown>
}

interface RawStyle {
  sources: Record<string, { type: string; [key: string]: unknown }>
  layers: RawLayer[]
  sprite?: unknown
  terrain?: unknown
  projection?: unknown
  sky?: unknown
  light?: unknown
  [key: string]: unknown
}

// route layers and their resting opacity (the loop fades them all out together before a replay)
export const ROUTE_OPACITY: Record<string, number> = {
  'hm-route-glow': CONFIG.route.glowOpacity,
  'hm-route-casing': 1,
  'hm-route-line': 1,
  'hm-route-ghost': CONFIG.route.ghostOpacity,
}

/**
 * Start from OpenFreeMap "bright", retint every layer to the palette, keep the map detail (parks,
 * water, road hierarchy, rail, names), add the 3D buildings and the route.
 */
export function restyle(input: unknown): StyleSpecification {
  const style = input as RawStyle
  const c = CONFIG.PALETTE
  const L = CONFIG.labels
  const vectorSource = Object.keys(style.sources).find((k) => style.sources[k].type === 'vector')
  if (!vectorSource) throw new Error('style has no vector source')
  // the style ships an unused low-zoom raster source; drop it so it can never cost a request
  for (const k of Object.keys(style.sources)) if (style.sources[k].type !== 'vector') delete style.sources[k]

  const FILL: Record<string, string> = {
    'landuse-cemetery': c.park,
    park: c.park,
    'landcover-grass': c.park,
    'landcover-grass-park': c.park,
    'landcover-wood': c.parkDeep,
    water: c.water,
    'water-intermittent': c.water,
    building: c.blocks,
    road_area_pier: c.ground,
    'highway-area': c.pedestrian,
    'aeroway-area': c.blocks,
  }
  const roadColor = (id: string): string => {
    const casing = /-casing$/.test(id)
    if (/path/.test(id)) return casing ? c.ground : c.path
    if (/motorway/.test(id)) return casing ? c.roadMajorCasing : c.roadMajor
    if (/trunk|primary|secondary|tertiary|(^|-)link/.test(id)) return casing ? c.roadCollectorCasing : c.roadCollector
    return casing ? c.roadMinorCasing : c.roadMinor
  }
  const text = (color: string, halo: string, width = 1.4): Record<string, unknown> => ({
    'text-color': color,
    'text-halo-color': halo,
    'text-halo-width': width,
  })

  const layers: RawLayer[] = []
  for (const layer of style.layers) {
    const id = layer.id
    const sl = layer['source-layer']
    if (layer.source && !style.sources[layer.source]) continue
    if (layer.type === 'background') {
      layer.paint = { 'background-color': c.ground }
      layers.push(layer)
      continue
    }

    if (layer.type === 'fill') {
      if (!(id in FILL)) continue // landuse tints, ice, sand, the fake-3D "building-top"
      layer.paint = { 'fill-color': FILL[id], 'fill-antialias': true }
      layers.push(layer)
      continue
    }

    if (layer.type === 'line') {
      if (sl === 'boundary' || /cablecar/.test(id)) continue
      let color: string
      if (sl === 'waterway') color = c.water
      else if (id === 'ferry') color = c.waterLabelHalo
      else if (/rail/.test(id)) color = c.rail
      else if (sl === 'aeroway') color = /casing/.test(id) ? c.roadMinorCasing : c.roadMinor
      else if (id === 'road_pier') color = c.ground
      else color = roadColor(id)
      layer.paint = { ...layer.paint, 'line-color': color }
      layers.push(layer)
      continue
    }

    if (layer.type === 'symbol') {
      // No sprite is loaded, so every kept label is text only.
      const lay: Record<string, unknown> = { ...layer.layout }
      for (const k of Object.keys(lay)) if (k.startsWith('icon-')) delete lay[k]
      if (id === 'highway-name-major' || id === 'highway-name-minor') {
        layer.minzoom = 13.5
        // bright has no name layer for motorways, so the major layer takes them too (Gardiner Expressway)
        const classes =
          id === 'highway-name-major' ? L.streetClasses.filter((k) => k !== 'minor') : L.streetClasses.filter((k) => k === 'minor')
        layer.filter = ['in', ['get', 'class'], ['literal', classes]]
        layer.layout = {
          ...lay,
          'text-size': id === 'highway-name-major' ? 12 : 11,
          'symbol-spacing': L.streetSpacing,
          'text-font': ['Noto Sans Regular'],
        }
        layer.paint = text(c.label, c.labelHalo)
      } else if (id === 'label_other') {
        // neighbourhood / area names
        layer.layout = {
          ...lay,
          'text-size': 12.5,
          'text-letter-spacing': 0.12,
          'text-transform': 'uppercase',
          'text-font': ['Noto Sans Regular'],
          'text-max-width': 7,
        }
        layer.paint = text(c.areaLabel, c.labelHalo, 1.6)
      } else if (id === 'poi_r1') {
        // parks, squares, landmarks
        layer.minzoom = 13.5
        layer.filter = ['all', ['in', ['get', 'class'], ['literal', L.poiClasses]], ['<=', ['get', 'rank'], L.poiMaxRank]]
        layer.layout = {
          ...lay,
          'text-size': 10.5,
          'text-letter-spacing': 0.06,
          'text-transform': 'uppercase',
          'text-font': ['Noto Sans Regular'],
          'text-anchor': 'center',
          'text-offset': [0, 0],
          'text-max-width': 7,
        }
        layer.paint = text(c.label, c.labelHalo)
      } else if (id === 'poi_transit') {
        // Union Station and the like
        layer.minzoom = 13.5
        layer.filter = ['all', ['==', ['get', 'class'], 'railway'], ['<=', ['get', 'rank'], 2]]
        layer.layout = {
          ...lay,
          'text-size': 10.5,
          'text-letter-spacing': 0.06,
          'text-transform': 'uppercase',
          'text-font': ['Noto Sans Regular'],
          'text-anchor': 'center',
          'text-offset': [0, 0],
        }
        layer.paint = text(c.label, c.labelHalo)
      } else if (sl === 'water_name' || sl === 'waterway') {
        // lake, slips, basins
        layer.layout = { ...lay, 'text-size': 12.5, 'text-letter-spacing': 0.04 }
        layer.paint = text(c.waterLabel, c.waterLabelHalo, 1.2)
      } else continue // arrows, shields, cities, countries, airports, minor POIs
      layers.push(layer)
    }
  }

  // 3D buildings: render_height / render_min_height from the OpenMapTiles `building` layer,
  // skipping features tagged hide_3d.
  const buildings3d: RawLayer = {
    id: 'hm-buildings-3d',
    type: 'fill-extrusion',
    source: vectorSource,
    'source-layer': 'building',
    minzoom: CONFIG.buildings.minzoom,
    filter: ['!=', ['get', 'hide_3d'], true],
    layout: { 'fill-extrusion-rounded-corner-distance': CONFIG.buildings.roundedCornerDistance },
    paint: {
      'fill-extrusion-color': ['interpolate', ['linear'], ['coalesce', ['get', 'render_height'], 0], ...c.buildingByHeight],
      'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 0],
      'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
      'fill-extrusion-opacity': CONFIG.buildings.opacity,
      'fill-extrusion-vertical-gradient': CONFIG.buildings.verticalGradient,
    },
  }

  const r = CONFIG.route
  const routeLayer = (id: string, paint: Record<string, unknown>): RawLayer => ({
    id,
    type: 'line',
    source: 'hm-route',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': c.route, ...paint },
  })
  const streetLevel = [
    routeLayer('hm-route-glow', { 'line-color': c.routeCasing, 'line-width': r.glowWidth, 'line-opacity': r.glowOpacity, 'line-blur': 8 }),
    routeLayer('hm-route-casing', { 'line-color': c.routeCasing, 'line-width': r.casingWidth, 'line-opacity': 1 }),
    routeLayer('hm-route-line', { 'line-width': r.width, 'line-opacity': 1 }),
  ]
  const ghost = routeLayer('hm-route-ghost', { 'line-width': r.ghostWidth, 'line-opacity': r.ghostOpacity })

  // Order matters: ground and roads, then the route ON the road, then the buildings (which hide
  // whatever is behind them), then the ghost, then the names.
  const firstSymbol = layers.findIndex((l) => l.type === 'symbol')
  layers.splice(firstSymbol === -1 ? layers.length : firstSymbol, 0, ...streetLevel, buildings3d, ghost)

  style.sources['hm-route'] = { type: 'geojson', data: routeGeoJson(1) }
  style.layers = layers
  style.light = { ...CONFIG.buildings.light, color: c.light }
  delete style.sprite // no icons are used, so skip the sprite sheet
  delete style.terrain
  delete style.projection
  delete style.sky
  return style as unknown as StyleSpecification
}
