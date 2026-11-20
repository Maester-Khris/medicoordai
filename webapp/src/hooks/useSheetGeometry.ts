import { useEffect, useState } from "react"
import { sheetGeometry, type SheetGeometry } from "../lib/sheetGeometry"

function read(): SheetGeometry {
  const vv = window.visualViewport
  return sheetGeometry({
    innerHeight: window.innerHeight,
    vvHeight: vv?.height ?? window.innerHeight,
    vvOffsetTop: vv?.offsetTop ?? 0,
  })
}

// Re-reads the sizes whenever the visual viewport changes (keyboard, rotation, browser bar).
export function useSheetGeometry(): SheetGeometry {
  const [geometry, setGeometry] = useState(read)
  useEffect(() => {
    const update = () => setGeometry(read())
    const vv = window.visualViewport
    vv?.addEventListener("resize", update)
    vv?.addEventListener("scroll", update)
    window.addEventListener("resize", update)
    return () => {
      vv?.removeEventListener("resize", update)
      vv?.removeEventListener("scroll", update)
      window.removeEventListener("resize", update)
    }
  }, [])
  return geometry
}
