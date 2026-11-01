import { formatWaitLabel } from "../../../utils/waitTimeUtils"
import { CATEGORY_STYLES, DEFAULT_STYLE } from '../config/categories'

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

interface UnifiedFacilityPopupProps {
  name:           string
  category:       string
  address:        string
  phone?:         string | null
  weekday_hours?: string[] | null
  distanceKm?:    number
  wait_minutes?:  number | null
  raw_wait?:      string | null
  predicted?:     boolean
}

export function UnifiedFacilityPopup({ name, category, address, phone, weekday_hours, distanceKm, wait_minutes, raw_wait, predicted }: UnifiedFacilityPopupProps) {
  const style = CATEGORY_STYLES[category] ?? DEFAULT_STYLE

  const today = DAYS[new Date().getDay()]
  const todayEntry = weekday_hours?.find(h => h.startsWith(`${today}:`))
  const todayHours = todayEntry ? todayEntry.replace(`${today}: `, '') : null
  const hasHoursData = weekday_hours && weekday_hours.length > 0
  const waitLabel = formatWaitLabel(wait_minutes, raw_wait, predicted)

  return (
    <div style={{ minWidth: 160, fontFamily: 'var(--font-sans)' }}>
      <p style={{ fontWeight: 700, fontSize: 13, marginBottom: 4, color: '#3D3A35' }}>
        {name}
      </p>
      <span style={{
        display: 'inline-block',
        background: style.color,
        color: 'white',
        fontSize: 10,
        fontWeight: 600,
        padding: '1px 6px',
        borderRadius: 4,
        marginBottom: 4,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}>
        {style.label}
      </span>
      <p style={{ fontSize: 11, color: '#7A756D', marginBottom: distanceKm != null ? 2 : 0 }}>
        {address}
      </p>
      {distanceKm != null && (
        <p style={{ fontSize: 11, color: '#7A756D' }}>~{distanceKm} km away</p>
      )}
      <div style={{ borderTop: '1px solid #DCD6CC', paddingTop: 6, marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <i className="ti ti-clock" style={{ fontSize: 11, color: '#8C8273' }} />
          <span style={{ fontSize: 10, color: '#7A756D', fontWeight: 500 }}>
            {hasHoursData
              ? (todayHours ?? 'Hours unavailable for today')
              : 'Hours unavailable'}
          </span>
        </div>
        {waitLabel && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <i className="ti ti-clock" style={{ fontSize: 11, color: '#8C8273' }} />
            <span style={{ fontSize: 10, color: '#7A756D', fontWeight: 500 }}>{waitLabel}</span>
          </div>
        )}
        {phone && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <i className="ti ti-phone" style={{ fontSize: 11, color: '#8C8273' }} />
            <a
              href={`tel:${phone}`}
              style={{ fontSize: 10, color: '#7A756D', fontWeight: 500, textDecoration: 'none' }}
            >
              {phone}
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
