import { useEffect, useState } from "react"
import type { AppConfig } from "@shared/types"
import { DEFAULT_CONFIG, getConfig } from "../lib/config"

export function useConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG)

  useEffect(() => {
    let cancelled = false
    void getConfig().then(loaded => { if (!cancelled) setConfig(loaded) })
    return () => { cancelled = true }
  }, [])

  return config
}
