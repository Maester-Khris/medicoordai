import "leaflet/dist/leaflet.css"
import L from "leaflet"
import { useState } from "react"
import { MapContainer, TileLayer, Marker, Tooltip } from "react-leaflet"
import type { Facility, FacilityCategory } from "@shared/types"
import { cnTowerPos, cartoTileUrl } from "../map/config/constants"
import { cnTowerIcon } from "../map/config/icons"

interface SandboxMapProps {
  facilities: Facility[]
  facilitiesLoading: boolean
}

const DARK_CATEGORY: Record<string, { color: string; letter: string }> = {
  hospital:    { color: "#E87070", letter: "H" },
  ambulatory:  { color: "#4DBFA0", letter: "A" },
  residential: { color: "#85A865", letter: "R" },
}

function getSandboxFacilityIcon(category: string): L.DivIcon {
  const s = DARK_CATEGORY[category] ?? { color: "#888888", letter: "?" }
  const size = 32, svg = 42, text = 14
  return L.divIcon({
    className: "",
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="${svg}" height="${svg}" viewBox="0 0 ${svg} ${svg}">
      <rect x="4" y="4" width="${size}" height="${size}" rx="${Math.round(size * 0.22)}"
            fill="${s.color}" />
      <text x="${svg / 2}" y="${svg / 2 + text * 0.38}"
            text-anchor="middle"
            font-family="system-ui,-apple-system,sans-serif"
            font-size="${text}" font-weight="700" fill="white">
        ${s.letter}
      </text>
    </svg>`,
    iconSize:    [svg, svg],
    iconAnchor:  [svg / 2, svg / 2],
    popupAnchor: [0, -(svg / 2 + 4)],
  })
}

type CategoryFilter = "all" | FacilityCategory

const FILTER_OPTIONS: Array<{ value: CategoryFilter; label: string }> = [
  { value: "all",         label: "All types" },
  { value: "hospital",    label: "Hospital" },
  { value: "ambulatory",  label: "Walk-in / Clinic" },
  { value: "residential", label: "Residential Care" },
]

const MOCK_ACTIVE_NODES = [
  [43.6532, -79.3832], // City Hall area
  [43.6400, -79.4000], // King West area
  [43.6600, -79.3700], // Cabbagetown area
  [43.6480, -79.3750], // Financial District
]

const MOCK_FACILITIES = [
  { id: "m1", name: "Toronto General", lat: 43.6590, lng: -79.3900, category: "hospital" as FacilityCategory },
  { id: "m2", name: "St. Michael's", lat: 43.6536, lng: -79.3781, category: "hospital" as FacilityCategory },
  { id: "m3", name: "Walk-in Clinic West", lat: 43.6450, lng: -79.4050, category: "ambulatory" as FacilityCategory },
  { id: "m4", name: "East End Clinic", lat: 43.6650, lng: -79.3500, category: "ambulatory" as FacilityCategory },
  { id: "m5", name: "Lakeshore Residential", lat: 43.6350, lng: -79.3950, category: "residential" as FacilityCategory },
  { id: "m6", name: "North Care", lat: 43.6700, lng: -79.3950, category: "residential" as FacilityCategory },
]

function getGlowingNodeIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="position: relative; width: 16px; height: 16px;">
      <div style="position: absolute; inset: -4px; border-radius: 50%; background: var(--sb-accent); opacity: 0.6; animation: sb-ping 2s cubic-bezier(0,0,0.2,1) infinite;"></div>
      <div style="position: relative; width: 16px; height: 16px; border-radius: 50%; background: var(--sb-accent); border: 2px solid var(--sb-bg-tertiary); box-shadow: 0 0 8px var(--sb-accent);"></div>
    </div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })
}

const LEGEND_ITEMS = [
  { color: "#E87070", letter: "H", label: "Hospital", type: "facility" },
  { color: "#4DBFA0", letter: "A", label: "Walk-in / Clinic", type: "facility" },
  { color: "#85A865", letter: "R", label: "Residential Care", type: "facility" },
  { color: "var(--sb-accent)", letter: "", label: "Simulated patient", type: "patient" },
]

export function SandboxMap({ facilities, facilitiesLoading }: SandboxMapProps) {
  const [filter, setFilter] = useState<CategoryFilter>("all")

  const effectiveFacilities = facilities.length > 0 ? facilities : MOCK_FACILITIES;

  const counts: Record<CategoryFilter, number> = {
    all:         effectiveFacilities.length,
    hospital:    effectiveFacilities.filter(f => f.category === "hospital").length,
    ambulatory:  effectiveFacilities.filter(f => f.category === "ambulatory").length,
    residential: effectiveFacilities.filter(f => f.category === "residential").length,
  }

  const displayed =
    filter === "all" ? effectiveFacilities : effectiveFacilities.filter(f => f.category === filter)

  return (
    <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
      <MapContainer
        center={cnTowerPos}
        zoom={11}
        scrollWheelZoom={false}
        zoomControl={true}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url={cartoTileUrl('dark_all')}
          tileSize={512}
          zoomOffset={-1}
          detectRetina={true}
        />
        <Marker position={cnTowerPos} icon={cnTowerIcon}>
          <Tooltip className="text-[14px] font-semibold" direction="top">
            CN Tower Area
          </Tooltip>
        </Marker>
        {displayed.map((facility, i) => (
          <Marker
            key={facility.id ?? `${facility.name}-${i}`}
            position={[facility.lat, facility.lng]}
            icon={getSandboxFacilityIcon(facility.category)}
          />
        ))}
        {MOCK_ACTIVE_NODES.map((pos, i) => (
          <Marker
            key={`mock-node-${i}`}
            position={pos as [number, number]}
            icon={getGlowingNodeIcon()}
          />
        ))}
      </MapContainer>

      {/* Loading spinner */}
      {facilitiesLoading && (
        <div
          style={{
            position: "absolute",
            top: 52,
            left: 12,
            zIndex: 1000,
            background: "rgba(15,17,23,0.88)",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 14,
            color: "var(--sb-text-secondary)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              border: "2px solid var(--sb-accent)",
              borderTopColor: "transparent",
              display: "inline-block",
              animation: "spin 0.8s linear infinite",
            }}
          />
          Loading facilities…
        </div>
      )}

      {/* Top-right overlay: filter dropdown + active count */}
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          zIndex: 20,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <select
          value={filter}
          onChange={e => setFilter(e.target.value as CategoryFilter)}
          style={{
            background: "rgba(15,17,23,0.88)",
            backdropFilter: "blur(4px)",
            border: "0.5px solid rgba(255,255,255,0.08)",
            borderRadius: 20,
            color: "#e8eaf0",
            fontSize: 14,
            fontWeight: 600,
            padding: "8px 16px",
            cursor: "pointer",
            outline: "none",
          }}
        >
          {FILTER_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>
              {opt.label} ({counts[opt.value]})
            </option>
          ))}
        </select>

        <div
          style={{
            background: "rgba(15,17,23,0.88)",
            backdropFilter: "blur(4px)",
            border: "0.5px solid rgba(255,255,255,0.08)",
            borderRadius: 20,
            padding: "8px 16px",
            fontSize: 14,
            fontWeight: 700,
            color: "#e8eaf0",
            display: "flex",
            alignItems: "center",
            gap: 10,
            pointerEvents: "none",
          }}
        >
          <span style={{ position: "relative", display: "inline-flex", width: 12, height: 12 }}>
            <span
              style={{
                position: "absolute",
                inset: 0,
                borderRadius: "50%",
                background: "var(--sb-accent)",
                opacity: 0.5,
                animation: "sb-ping 1.5s cubic-bezier(0,0,0.2,1) infinite",
              }}
            />
            <span
              style={{
                position: "relative",
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "var(--sb-accent)",
              }}
            />
          </span>
          {facilitiesLoading ? "—" : displayed.length} FACILITIES ACTIVE
        </div>
      </div>

      {/* Bottom-left legend */}
      <div
        style={{
          position: "absolute",
          bottom: 16,
          left: 16,
          zIndex: 400,
          background: "rgba(15,17,23,0.88)",
          backdropFilter: "blur(4px)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: 8,
          padding: "12px 16px",
          display: "flex",
          flexDirection: "row",
          gap: 16,
          boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
        }}
      >
        {LEGEND_ITEMS.map(item => (
          <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {item.type === "patient" ? (
              <div style={{ width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <div style={{ position: "relative", width: 12, height: 12 }}>
                  <div style={{ position: "absolute", inset: -3, borderRadius: "50%", background: item.color, opacity: 0.6 }}></div>
                  <div style={{ position: "relative", width: 12, height: 12, borderRadius: "50%", background: item.color, border: "2px solid rgba(15,23,42,0.8)" }}></div>
                </div>
              </div>
            ) : (
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 4,
                  background: item.color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "white",
                  flexShrink: 0,
                }}
              >
                {item.letter}
              </div>
            )}
            <span style={{ fontSize: 13, color: "var(--sb-text-primary)", fontWeight: 500 }}>{item.label}</span>
          </div>
        ))}
      </div>

      {/* Background Watermark */}
      <div
        style={{
          position: "absolute",
          bottom: "15%",
          right: "5%",
          transform: "rotate(-12deg)",
          fontSize: 100,
          fontWeight: 800,
          letterSpacing: "0.2em",
          color: "rgba(255, 255, 255, 0.04)",
          pointerEvents: "none",
          userSelect: "none",
          whiteSpace: "nowrap",
          zIndex: 400,
        }}
      >
        TORONTO
      </div>

    </div>
  )
}
