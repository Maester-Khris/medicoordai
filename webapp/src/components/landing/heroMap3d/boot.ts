import type { GeoJSONSource, Map as MapLibreMap, Marker as MapLibreMarker } from 'maplibre-gl'
// MapLibre 6 locates its worker next to its own file, which breaks once a bundler moves the module.
// `?worker&url` has Vite bundle the worker (with its shared chunk) and hand back a URL for setWorkerUrl.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { CONFIG, FACILITIES, ROUTE, USER, type CameraView, type LngLat } from './config'
import { chipElement, el, pinElement, userElement } from './dom'
import { clamp01, easeInOut, routeGeoJson } from './route'
import { restyle, ROUTE_OPACITY } from './style'

export interface HeroMapRefs {
  root: HTMLElement
  mapEl: HTMLElement
  fallbackEl: HTMLElement
  fallbackSvg: SVGSVGElement
  toggleBtn: HTMLButtonElement
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

/**
 * Starts the hero map inside the given elements and returns a disposer. Safe to call twice in a row
 * (React StrictMode): the disposer stops everything the call started.
 */
export function startHeroMap(refs: HeroMapRefs): () => void {
  // The build's prerender step renders this page where matchMedia does not exist; there is no map to start.
  if (typeof window.matchMedia !== 'function') return () => {}
  const { root, mapEl, fallbackEl, fallbackSvg, toggleBtn } = refs
  const P = CONFIG.PALETTE
  const disposers: Array<() => void> = []
  let disposed = false

  // One palette for everything: the map style reads CONFIG.PALETTE directly, the CSS reads these variables.
  const cssVars: Record<string, string> = {
    '--hm-haze': P.page,
    '--hm-ground': P.ground,
    '--hm-route': P.route,
    '--hm-chrome': P.chrome,
    '--hm-chrome-hover': P.chromeHover,
    '--hm-chrome-text': P.chromeText,
    '--hm-chrome-text-dim': P.chromeTextDim,
    '--hm-mint': P.mint,
    '--hm-mint-ink': P.mintInk,
    '--hm-marker-label': P.markerLabel,
    '--hm-hospital': P.hospital,
    '--hm-walkin': P.walkin,
    '--hm-residential': P.residential,
  }
  for (const [name, value] of Object.entries(cssVars)) root.style.setProperty(name, value)

  const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  const mobileQuery = window.matchMedia('(max-width: 600px)')
  const cameraFor = (): CameraView => (mobileQuery.matches ? CONFIG.camera.mobile : CONFIG.camera.desktop)

  /* ---------------- static fallback: plain light panel, route as inline SVG, chip ---------------- */
  let fallbackShown = false
  function showFallback(reason: string): void {
    if (fallbackShown || disposed) return
    fallbackShown = true
    console.warn(`[hero-map] static fallback: ${reason}`)
    root.dataset.state = 'fallback'
    root.classList.add('is-paused', 'chip-on')
    mapEl.hidden = true
    toggleBtn.hidden = true // nothing moves, so nothing to pause
    fallbackEl.hidden = false

    const draw = (): void => {
      for (const node of Array.from(fallbackEl.querySelectorAll('.hm-user, .hm-pin, .hm-chip'))) node.remove()
      const { width: W, height: H } = fallbackEl.getBoundingClientRect()
      if (!W || !H) return
      const narrow = mobileQuery.matches

      // Plan view: rotate by the angle of Toronto's street grid so the streets come out square to
      // the panel, then fit the route and the pins inside the panel.
      const rot = (16.7 * Math.PI) / 180
      const kx = Math.cos((43.65 * Math.PI) / 180)
      const flat = ([lng, lat]: [number, number]): [number, number] => {
        const x = lng * kx
        const y = lat
        return [x * Math.cos(rot) + y * Math.sin(rot), x * Math.sin(rot) - y * Math.cos(rot)]
      }
      const all = [...ROUTE, ...FACILITIES.map((f) => f.lngLat)].map(flat)
      const xs = all.map((p) => p[0])
      const ys = all.map((p) => p[1])
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      const pad = narrow ? { l: 60, r: 150, t: 150, b: 90 } : { l: 190, r: 300, t: 150, b: 110 }
      const scale = Math.min((W - pad.l - pad.r) / (maxX - minX), (H - pad.t - pad.b) / (maxY - minY))
      const offX = pad.l + (W - pad.l - pad.r - (maxX - minX) * scale) / 2
      const offY = pad.t + (H - pad.t - pad.b - (maxY - minY) * scale) / 2
      const project = (lngLat: [number, number]): [number, number] => {
        const [x, y] = flat(lngLat)
        return [offX + (x - minX) * scale, offY + (y - minY) * scale]
      }

      const pts = ROUTE.map(project)
      const line = pts.map((p) => p.map((n) => n.toFixed(1)).join(',')).join(' ')
      // faint streets: one line each way through every turn / crossing on the route
      const streets: string[] = []
      const vx: number[] = []
      const hy: number[] = []
      for (const [x, y] of pts.slice(1, -1)) {
        if (!vx.some((v) => Math.abs(v - x) < 24)) vx.push(x)
        if (!hy.some((v) => Math.abs(v - y) < 24)) hy.push(y)
      }
      for (const x of vx) streets.push(`<line x1="${x.toFixed(1)}" y1="0" x2="${x.toFixed(1)}" y2="${H}"/>`)
      for (const y of hy) streets.push(`<line x1="0" y1="${y.toFixed(1)}" x2="${W}" y2="${y.toFixed(1)}"/>`)
      const [ux, uy] = project(USER.lngLat)

      fallbackSvg.setAttribute('viewBox', `0 0 ${W} ${H}`)
      fallbackSvg.innerHTML = `
        <rect width="${W}" height="${H}" fill="${P.ground}"/>
        <g stroke="${P.roadMinorCasing}" stroke-width="12">${streets.join('')}</g>
        <g stroke="${P.roadMinor}" stroke-width="9">${streets.join('')}</g>
        <polyline points="${line}" fill="none" stroke="${P.routeCasing}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
        <polyline points="${line}" fill="none" stroke="${P.route}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>`

      // labels, pins and the chip are HTML on top of the SVG (real text, same styles as the live map)
      const place = (node: HTMLElement, [x, y]: [number, number], transform: string): void => {
        node.style.position = 'absolute'
        node.style.left = `${x}px`
        node.style.top = `${y}px`
        node.style.transform = transform
        fallbackEl.append(node)
      }
      place(userElement(), [ux, uy], 'translate(-50%, -50%)')
      for (const f of FACILITIES) place(pinElement(f, !f.dest), project(f.lngLat), 'translate(-50%, -50%)')
      const [dx, dy] = project(FACILITIES[0].lngLat)
      place(chipElement(), narrow ? [dx + 26, dy - 34] : [dx + 34, dy], narrow ? 'translate(-100%, -100%)' : 'translate(0, -50%)')
    }
    draw()
    const observer = new ResizeObserver(draw)
    observer.observe(fallbackEl)
    disposers.push(() => observer.disconnect())
  }

  /* ---------------- live map ---------------- */
  async function boot(): Promise<void> {
    if (!webglAvailable()) return showFallback('WebGL is not available')

    let maplibre: typeof import('maplibre-gl')
    let styleJson: unknown
    try {
      // dynamic import: MapLibre loads in its own chunk, so it never blocks the first paint, and a
      // failure lands in the static fallback instead of a dead hero
      ;[maplibre, styleJson] = await Promise.all([
        import('maplibre-gl'),
        fetch(CONFIG.styleUrl).then((r) => {
          if (!r.ok) throw new Error(`style HTTP ${r.status}`)
          return r.json() as Promise<unknown>
        }),
      ])
    } catch (err) {
      return showFallback(`could not load MapLibre or the style (${err instanceof Error ? err.message : String(err)})`)
    }
    if (disposed) return
    maplibre.setWorkerUrl(maplibreWorkerUrl)

    let map: MapLibreMap
    try {
      map = new maplibre.Map({
        container: mapEl,
        style: restyle(styleJson),
        ...cameraFor(),
        interactive: false, // a hero visual: it must not trap scroll or keyboard focus
        attributionControl: false, // added below, always expanded
        maxPitch: 70,
        fadeDuration: 0,
      })
    } catch (err) {
      return showFallback(`map failed to start (${err instanceof Error ? err.message : String(err)})`)
    }
    disposers.push(() => {
      try {
        map.remove()
      } catch {
        // already removed (fallback path)
      }
    })
    // compact:false keeps the full credit line visible at every width instead of collapsing to an "i"
    map.addControl(new maplibre.AttributionControl({ compact: false }), 'bottom-right')

    // Fit the camera to the route and pins for the panel's actual size, leaving room for the chip
    // (right of the destination on wide panels, above it on narrow ones) and the pause button.
    const points = [...ROUTE, USER.lngLat, ...FACILITIES.map((f) => f.lngLat)]
    const bounds: [LngLat, LngLat] = [
      [Math.min(...points.map((p) => p[0])), Math.min(...points.map((p) => p[1]))],
      [Math.max(...points.map((p) => p[0])), Math.max(...points.map((p) => p[1]))],
    ]
    const fitCamera = (): void => {
      const view = cameraFor()
      const narrow = mobileQuery.matches
      const padding = narrow ? { top: 150, bottom: 70, left: 50, right: 50 } : { top: 130, bottom: 80, left: 90, right: 260 }
      const cam = map.cameraForBounds(bounds, { padding, bearing: view.bearing, maxZoom: CONFIG.camera.maxFitZoom })
      if (cam) map.jumpTo({ ...cam, bearing: view.bearing, pitch: view.pitch })
    }
    fitCamera()
    const resizeObserver = new ResizeObserver(() => fitCamera())
    resizeObserver.observe(root)
    disposers.push(() => resizeObserver.disconnect())

    let loaded = false
    const giveUp = (reason: string): void => {
      if (loaded || disposed) return
      try {
        map.remove()
      } catch {
        // ignore
      }
      showFallback(reason)
    }
    const timer = window.setTimeout(() => giveUp('map did not load in time'), CONFIG.loadTimeoutMs)
    disposers.push(() => window.clearTimeout(timer))
    map.on('error', (e) => giveUp(`map error before first load (${e.error?.message ?? 'unknown'})`))

    // The canvas is a picture: give it a text alternative and take it out of the tab order.
    const canvas = map.getCanvas()
    canvas.setAttribute('role', 'img')
    canvas.setAttribute('aria-label', 'Stylised 3D map of downtown Toronto with a sample route to a hospital')
    canvas.removeAttribute('tabindex')
    canvas.after(el('div', 'hero-map__haze')) // markers are appended later, so they stay above it

    /* ---- markers ---- */
    new maplibre.Marker({ element: userElement(), anchor: 'center' }).setLngLat(USER.lngLat).addTo(map)
    for (const f of FACILITIES) new maplibre.Marker({ element: pinElement(f), anchor: 'center' }).setLngLat(f.lngLat).addTo(map)
    // The chip floats beside the destination pin: right of it on wide panels, above-left on narrow
    // ones so it stays inside the crop. Marker anchors are fixed at creation, hence the rebuild.
    let chipMarker: MapLibreMarker | undefined
    const placeChip = (): void => {
      chipMarker?.remove()
      const narrow = mobileQuery.matches
      chipMarker = new maplibre.Marker({
        element: chipElement(),
        anchor: narrow ? 'bottom-right' : 'left',
        offset: narrow ? [26, -34] : [34, 0],
      })
        .setLngLat(FACILITIES[0].lngLat)
        .addTo(map)
    }
    placeChip()

    /* ---- timeline: every visual is a pure function of `clock` (ms), so pause == stop the clock ---- */
    const A = CONFIG.animation
    const cycleMs = A.drawMs + A.holdMs + A.fadeMs
    let clock = 0
    let driftClock = 0
    let playing = false
    let visible = true
    let raf = 0
    let last = 0
    let shownProgress = -1
    let shownOpacity = -1

    const render = (): void => {
      const t = A.loop && !reducedMotionQuery.matches ? clock % cycleMs : Math.min(clock, A.drawMs + A.holdMs)
      const progress = easeInOut(clamp01(t / A.drawMs))
      const fading = t > A.drawMs + A.holdMs
      const opacity = fading ? 1 - clamp01((t - A.drawMs - A.holdMs) / A.fadeMs) : 1
      if (progress !== shownProgress) {
        ;(map.getSource('hm-route') as GeoJSONSource | undefined)?.setData(routeGeoJson(progress))
        shownProgress = progress
      }
      if (opacity !== shownOpacity) {
        for (const [id, base] of Object.entries(ROUTE_OPACITY)) map.setPaintProperty(id, 'line-opacity', opacity * base)
        shownOpacity = opacity
      }
      root.classList.toggle('chip-on', t >= A.drawMs && !fading)
      if (A.drift.degrees && !reducedMotionQuery.matches) {
        map.setBearing(cameraFor().bearing + A.drift.degrees * Math.sin((driftClock / A.drift.periodMs) * 2 * Math.PI))
      }
    }

    const setPlaying = (next: boolean): void => {
      playing = next
      // replay from the start if the user presses play on a finished, non-looping run
      if (playing && (!A.loop || reducedMotionQuery.matches) && clock >= A.drawMs + A.holdMs) clock = 0
      root.classList.toggle('is-paused', !playing)
      toggleBtn.setAttribute('aria-label', playing ? 'Pause map animation' : 'Play map animation')
      syncLoop()
    }
    const frame = (now: number): void => {
      const dt = Math.min(now - last, 250) // clamp so one long stall cannot skip the whole draw
      last = now
      clock += dt
      driftClock += dt
      render()
      const finished = (!A.loop || reducedMotionQuery.matches) && clock >= A.drawMs + A.holdMs
      if (finished) return setPlaying(false)
      raf = requestAnimationFrame(frame)
    }
    function syncLoop(): void {
      cancelAnimationFrame(raf)
      if (playing && visible && !document.hidden) {
        last = performance.now()
        raf = requestAnimationFrame(frame)
      }
    }
    const showFinalState = (): void => {
      clock = A.drawMs
      render()
    }
    const applyBreakpoint = (): void => {
      // narrow screens: fewer map labels
      for (const id of CONFIG.labels.hideOnMobile) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', mobileQuery.matches ? 'none' : 'visible')
      }
    }

    const onToggle = (): void => setPlaying(!playing)
    toggleBtn.addEventListener('click', onToggle)
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      syncLoop()
    })
    observer.observe(root) // do not burn frames while the hero is off screen
    const onVisibility = (): void => syncLoop()
    document.addEventListener('visibilitychange', onVisibility)
    const onReducedMotion = (): void => {
      if (reducedMotionQuery.matches) {
        setPlaying(false)
        map.setBearing(cameraFor().bearing)
        showFinalState()
      }
    }
    reducedMotionQuery.addEventListener('change', onReducedMotion)
    const onBreakpoint = (): void => {
      fitCamera()
      placeChip()
      applyBreakpoint()
    }
    mobileQuery.addEventListener('change', onBreakpoint)
    disposers.push(() => {
      cancelAnimationFrame(raf)
      toggleBtn.removeEventListener('click', onToggle)
      observer.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      reducedMotionQuery.removeEventListener('change', onReducedMotion)
      mobileQuery.removeEventListener('change', onBreakpoint)
    })

    map.on('load', () => {
      loaded = true
      window.clearTimeout(timer)
      root.dataset.state = 'ready'
      toggleBtn.hidden = false
      applyBreakpoint()
      if (reducedMotionQuery.matches) {
        // reduced motion: final state, no autoplay, no camera motion. Play still works on request.
        showFinalState()
      } else {
        clock = 0
        render()
        setPlaying(true)
      }
    })
  }

  void boot()

  return () => {
    disposed = true
    for (const dispose of disposers.splice(0).reverse()) dispose()
    // leave the host in its initial state for a re-mount (React StrictMode mounts twice in dev)
    for (const node of Array.from(fallbackEl.querySelectorAll('.hm-user, .hm-pin, .hm-chip'))) node.remove()
    fallbackSvg.innerHTML = ''
    root.classList.remove('chip-on')
    root.classList.add('is-paused')
    delete root.dataset.state
    mapEl.hidden = false
    fallbackEl.hidden = true
    toggleBtn.hidden = true
  }
}
