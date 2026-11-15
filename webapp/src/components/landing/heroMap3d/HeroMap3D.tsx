import { useEffect, useRef } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import './HeroMap3D.css'
import { startHeroMap } from './boot'
import { ARIA_LABEL } from './config'

/**
 * Live 3D map of downtown Toronto for the landing hero: extruded buildings, a sample route to the
 * nearest emergency room and a facility chip. Framed as a product-preview card with a crisp border
 * and subtle glow. MapLibre loads in its own chunk after mount; with no WebGL, or if the tiles
 * fail, a static drawing is shown instead. All distances and waits are sample values.
 */
export function HeroMap3D() {
  const rootRef = useRef<HTMLElement>(null)
  const mapRef = useRef<HTMLDivElement>(null)
  const fallbackRef = useRef<HTMLDivElement>(null)
  const fallbackSvgRef = useRef<SVGSVGElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const root = rootRef.current
    const mapEl = mapRef.current
    const fallbackEl = fallbackRef.current
    const fallbackSvg = fallbackSvgRef.current
    const toggleBtn = toggleRef.current
    if (!root || !mapEl || !fallbackEl || !fallbackSvg || !toggleBtn) return
    return startHeroMap({ root, mapEl, fallbackEl, fallbackSvg, toggleBtn })
  }, [])

  return (
    <section ref={rootRef} className="hero-map is-paused" role="group" aria-label={ARIA_LABEL}>
      {/* first in DOM order so it is the first tab stop of the element */}
      <button ref={toggleRef} className="hero-map__toggle" type="button" aria-label="Play map animation" hidden>
        <svg className="icon-pause" viewBox="0 0 18 18" aria-hidden="true">
          <rect x="3.5" y="2.5" width="4" height="13" rx="1" />
          <rect x="10.5" y="2.5" width="4" height="13" rx="1" />
        </svg>
        <svg className="icon-play" viewBox="0 0 18 18" aria-hidden="true">
          <path d="M5 2.6v12.8a.6.6 0 0 0 .92.5l9.9-6.4a.6.6 0 0 0 0-1L5.92 2.1A.6.6 0 0 0 5 2.6z" />
        </svg>
      </button>

      <div ref={mapRef} className="hero-map__map" />

      <div ref={fallbackRef} className="hero-map__fallback" hidden>
        <svg
          ref={fallbackSvgRef}
          role="img"
          aria-label="Simplified static drawing of the sample route from your location to St. Michael's Hospital."
        />
        <span className="hero-map__fallback-credit">Static illustration, not a live map</span>
      </div>

      <div className="hero-map__vignette" aria-hidden="true" />
    </section>
  )
}
