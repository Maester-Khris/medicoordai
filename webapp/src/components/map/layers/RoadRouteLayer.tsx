import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import type { RouteResult } from '../../../../../shared/types'
import { useMapContext } from '../context/MapContext'
import { buildTriageCandidates } from '../config/constants'
import { CATEGORY_STYLES, DEFAULT_STYLE } from '../config/categories'
import { getFacilitySvgInner } from '../config/icons'

const STYLE_ID = "road-route-layer-styles"

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return
  const el = document.createElement("style")
  el.id = STYLE_ID
  el.textContent = `
    @keyframes routeFlow {
      from { stroke-dashoffset: 0; }
      to   { stroke-dashoffset: -17; }
    }
    @keyframes originHalo {
      0%   { transform: scale(0.5); opacity: 0.7; }
      100% { transform: scale(2.4); opacity: 0; }
    }
    .route-flow-line {
      animation: routeFlow 3s linear infinite;
    }
    .origin-pulse-halo {
      animation: originHalo 2s ease-out infinite;
    }
    @media (prefers-reduced-motion: reduce) {
      .route-flow-line    { animation: none; }
      .origin-pulse-halo  { animation: none; opacity: 0.12; }
    }
  `
  document.head.appendChild(el)
}

function buildOriginIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `
      <div style="position:relative;width:40px;height:40px">
        <div class="origin-pulse-halo" style="
          position:absolute;inset:0;border-radius:50%;
          background:#48F6C1;pointer-events:none"></div>
        <div style="
          position:absolute;top:50%;left:50%;width:18px;height:18px;
          border-radius:50%;background:rgba(6,18,25,0.95);
          border:2px solid rgba(72,246,193,0.6);
          box-shadow:0 0 10px rgba(72,246,193,0.3);
          transform:translate(-50%,-50%);pointer-events:none"></div>
        <div style="
          position:absolute;top:50%;left:50%;width:9px;height:9px;
          border-radius:50%;background:#48F6C1;
          transform:translate(-50%,-50%);pointer-events:none"></div>
      </div>`,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  })
}

function buildDestinationIcon(
  category: string,
  color: string,
  etaLabel: string | null,
): L.DivIcon {
  const chip = etaLabel
    ? `<div style="
        margin-top:4px;white-space:nowrap;
        background:rgba(6,18,25,0.9);
        border:1px solid rgba(28,70,89,0.7);border-radius:999px;
        padding:3px 10px;font-size:11px;font-weight:600;color:#E2F1F5;
        backdrop-filter:blur(8px);line-height:1.5;
        font-family:system-ui,-apple-system,sans-serif;
        pointer-events:none">${etaLabel}</div>`
    : ""

  return L.divIcon({
    className: "",
    html: `
      <div style="
        display:inline-flex;flex-direction:column;align-items:center;
        pointer-events:none">
        <div style="
          position:relative;
          width:38px;height:38px;border-radius:50%;background:${color};
          border:2px solid rgba(255,255,255,0.2);display:flex;align-items:center;
          justify-content:center;box-shadow:0 0 12px ${color}66,0 3px 10px rgba(0,0,0,0.4)">
          <div class="user-pulse-halo" style="
            position:absolute;inset:-6px;border-radius:50%;
            border:2px solid ${color};
            pointer-events:none;
          "></div>
          <svg width="38" height="38" viewBox="0 0 38 38" style="display:block;position:relative;z-index:2">
            ${getFacilitySvgInner(category, 38)}
          </svg>
        </div>
        <div style="
          width:0;height:0;border-left:7px solid transparent;
          border-right:7px solid transparent;
          border-top:9px solid ${color};margin-top:-1px;
          position:relative;z-index:2;
          pointer-events:none"></div>
        ${chip}
      </div>`,
    iconSize: etaLabel ? [120, 76] : [44, 48],
    iconAnchor: etaLabel ? [60, 46] : [22, 46],
    popupAnchor: [0, -50],
  })
}

const NO_ROUTES: RouteResult[] = []

export function RoadRouteLayer() {
  const map = useMap()
  const { activeTriage, recommendedId } = useMapContext()
  const layerRef = useRef<L.LayerGroup | null>(null)

  const triageCandidates    = buildTriageCandidates(activeTriage)
  const recommendedFacility = activeTriage.active
    ? triageCandidates.find(f => f.id === recommendedId)
    : undefined

  const userCoords   = activeTriage.active ? activeTriage.userCoords   : null
  const roadGeometry = activeTriage.active ? activeTriage.roadGeometry : null
  const routes       = activeTriage.active ? activeTriage.routes       : NO_ROUTES

  useEffect(() => {
    if (layerRef.current) {
      layerRef.current.remove()
      layerRef.current = null
    }

    if (!userCoords || !recommendedFacility) return

    ensureStyles()

    const { lat: userLat, lng: userLng } = userCoords
    const { lat: facilityLat, lng: facilityLng } = recommendedFacility

    const positions: [number, number][] =
      roadGeometry && roadGeometry.length > 1
        ? roadGeometry
        : [[userLat, userLng], [facilityLat, facilityLng]]

    console.log(
      "[MapPanel] polyline mode:",
      roadGeometry ? "road geometry" : "straight line fallback",
      "points:", positions.length
    )

    const ROUND = { lineCap: "round" as const, lineJoin: "round" as const, smoothFactor: 1 }

    const shadow = L.polyline(positions, { ...ROUND, color: "#48F6C1", weight: 16, opacity: 0.15 })
    const casing = L.polyline(positions, { ...ROUND, color: "#061219", weight: 8,  opacity: 0.85 })
    const main   = L.polyline(positions, { ...ROUND, color: "#48F6C1", weight: 4,  opacity: 1.0 })
    const flow   = L.polyline(positions, {
      ...ROUND,
      color: "rgba(255,255,255,0.75)",
      weight: 1.5,
      opacity: 1,
      dashArray: "8 16",
      className: "route-flow-line",
    })

    const originMarker = L.marker([userLat, userLng], {
      icon: buildOriginIcon(),
      zIndexOffset: 100,
    })

    const route = routes.find(r => r.facilityId === recommendedFacility.id)
    const etaLabel = route ? `${route.etaMinutes} min · ${route.distanceKm} km` : null
    const catStyle = CATEGORY_STYLES[recommendedFacility.category] ?? DEFAULT_STYLE
    const destMarker = L.marker([facilityLat, facilityLng], {
      icon: buildDestinationIcon(recommendedFacility.category, catStyle.color, etaLabel),
      zIndexOffset: 200,
    })

    // Draw secondary connectors to alternative recommendations
    const secondaryCandidates = triageCandidates.filter(f => f.id !== recommendedFacility.id)
    const secondaryLayers: L.Layer[] = []

    secondaryCandidates.forEach(cand => {
      const candRoute = routes.find(r => r.facilityId === cand.id)
      const candEtaLabel = candRoute ? `Alt: ${candRoute.etaMinutes} min` : null
      const candStyle = CATEGORY_STYLES[cand.category] ?? DEFAULT_STYLE
      // Real road shape when the backend routed this alternative, straight connector otherwise.
      const candPositions: [number, number][] =
        candRoute?.geometry && candRoute.geometry.length > 1
          ? candRoute.geometry
          : [[userLat, userLng], [cand.lat, cand.lng]]

      const candLine = L.polyline(candPositions, {
        ...ROUND,
        color: "#7AA0B0",
        weight: 2,
        opacity: 0.65,
        dashArray: "6 10",
      })
      secondaryLayers.push(candLine)

      const candMarker = L.marker([cand.lat, cand.lng], {
        icon: buildDestinationIcon(cand.category, candStyle.color, candEtaLabel),
        zIndexOffset: 150,
      })
      secondaryLayers.push(candMarker)
    })

    layerRef.current = L.layerGroup([
      shadow,
      casing,
      main,
      flow,
      originMarker,
      destMarker,
      ...secondaryLayers,
    ])
    layerRef.current.addTo(map)

    const bounds = main.getBounds().extend([facilityLat, facilityLng])
    map.fitBounds(bounds, {
      paddingTopLeft:     [60, 80],
      paddingBottomRight: [100, 60],
      maxZoom: 14,
    })

    setTimeout(() => map.invalidateSize(), 100)

    return () => {
      if (layerRef.current) {
        layerRef.current.remove()
        layerRef.current = null
      }
    }
  }, [map, userCoords?.lat, userCoords?.lng, recommendedFacility?.lat, recommendedFacility?.lng, roadGeometry, routes])

  return null
}
