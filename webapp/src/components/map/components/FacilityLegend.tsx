import { LEGEND_ITEMS } from '../config/categories'
import { getFacilitySvgInner } from '../config/icons'

// bottomInset lifts the legend above the mobile bottom sheet, which covers the bottom of the map.
export function FacilityLegend({ verticalLegend, bottomInset = 0 }: { verticalLegend: boolean; bottomInset?: number }) {
  return (
    <div style={{
      position: 'absolute',
      bottom: 12 + bottomInset,
      left: 12,
      zIndex: 15,
      background: 'rgba(6, 18, 25, 0.85)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: '1px solid rgba(28, 70, 89, 0.6)',
      borderRadius: 10,
      padding: '10px 14px',
      pointerEvents: 'none',
    }}>
      <p style={{
        fontSize: 10,
        fontWeight: 700,
        color: '#7AA0B0',
        marginBottom: 8,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
      }}>
        Legend
      </p>
      <div style={verticalLegend
        ? { display: 'flex', flexDirection: 'column', gap: 7 }
        : { display: 'flex', alignItems: 'center', gap: 14 }
      }>
        {LEGEND_ITEMS.map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            {'isPin' in item ? (
              <span style={{
                position: 'relative',
                width: 14,
                height: 14,
                borderRadius: '50%',
                background: 'white',
                border: '2.5px solid #48F6C1',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                boxShadow: `0 0 6px #48F6C188`,
              }}>
                <span style={{
                  width: 4,
                  height: 4,
                  borderRadius: '50%',
                  background: '#48F6C1',
                  display: 'inline-block',
                }} />
              </span>
            ) : (
              <span style={{
                width: 18,
                height: 18,
                borderRadius: '50%',
                background: item.color,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                boxShadow: `0 0 6px ${'color' in item ? item.color : ''}55`,
              }}>
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 18 18"
                  dangerouslySetInnerHTML={{
                    __html: getFacilitySvgInner(
                      item.letter === 'H' ? 'hospital' : item.letter === 'A' ? 'ambulatory' : 'residential',
                      18
                    )
                  }}
                />
              </span>
            )}
            <span style={{ fontSize: 11, fontWeight: 600, color: '#A0B8C4', lineHeight: 1 }}>
              {item.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
