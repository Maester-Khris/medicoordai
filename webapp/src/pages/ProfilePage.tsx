import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { MobileTopBar } from '../components/mobile/MobileTopBar'
import { DrawerMenu } from '../components/mobile/DrawerMenu'
import { RadioCard } from '../components/onboarding/fields/RadioCard'
import { TextField } from '../components/onboarding/fields/TextField'
import { SelectField } from '../components/onboarding/fields/SelectField'
import { ToggleRow } from '../components/onboarding/fields/ToggleRow'
import { BLOOD_TYPE_OPTIONS, AI_ASSISTANT_OPT_IN_COPY } from '../components/onboarding/steps/MedicalProfileStep'
import { useAuth } from '../auth/useAuth'
import { useProfile } from '../hooks/useProfile'
import { useNotificationPermission } from '../hooks/useNotificationPermission'
import { apiFetch } from '../lib/apiClient'
import { formatDisplayName } from '../lib/formatDisplayName'
import { trimOrNull } from '../lib/trimOrNull'
import type { NotificationDevice } from '@shared/types'
import {
  User,
  SignOut,
  ShieldCheck,
  Compass,
  MapPin,
  Watch,
  DeviceMobile,
  Phone,
  Folder,
  ArrowSquareOut,
  Plus
} from '@phosphor-icons/react'
import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { MapContainer, TileLayer, Marker } from 'react-leaflet'
import { cartoTileUrl } from '../components/map/config/constants'

const MOUNT_SINAI_POS: [number, number] = [43.6579, -79.3873]

const miniMapPinIcon = L.divIcon({
  className: '',
  html: `<div style="width:14px;height:14px;border-radius:50%;background:#48F6C1;border:2px solid #061219;box-shadow:0 0 0 4px rgba(72,246,193,0.25);"></div>`,
  iconSize: [14, 14],
  iconAnchor: [7, 7],
})

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      className="flex flex-col gap-4"
      style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, padding: 20 }}
    >
      <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}>
        {title}
      </h2>
      {children}
    </div>
  )
}

export default function ProfilePage() {
  const isMobile = useBreakpoint()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const { user } = useAuth()
  const { profile, updateProfile } = useProfile()
  const { permissionState, requesting, requestPermission } = useNotificationPermission(user?.id ?? null)

  const [locationPref, setLocationPref] = useState<'always' | 'ask'>('ask')
  const [contactName, setContactName] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [autoAlertOptIn, setAutoAlertOptIn] = useState(false)
  const [allergies, setAllergies] = useState('')
  const [conditions, setConditions] = useState('')
  const [bloodType, setBloodType] = useState('')
  const [chatOptIn, setChatOptIn] = useState(false)
  const [devices, setDevices] = useState<NotificationDevice[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!profile) return
    setLocationPref(profile.location_preference)
    setContactName(profile.emergency_contact_name ?? '')
    setContactPhone(profile.emergency_contact_phone ?? '')
    setAutoAlertOptIn(profile.auto_alert_opt_in)
    setAllergies(profile.allergies ?? '')
    setConditions(profile.conditions ?? '')
    setBloodType(profile.blood_type ?? '')
    setChatOptIn(profile.medical_chat_opt_in)
  }, [profile])

  useEffect(() => {
    if (!user) return
    apiFetch('/notifications/devices')
      .then(res => res.ok ? res.json() : { devices: [] })
      .then(data => setDevices(data.devices ?? []))
      .catch(() => setDevices([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  const removeDevice = async (subscriptionId: string) => {
    const previous = devices
    setDevices(current => current.filter(d => d.subscription_id !== subscriptionId))
    try {
      const res = await apiFetch(`/notifications/devices/${subscriptionId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to remove device (${res.status})`)
    } catch {
      setDevices(previous)
      setSaveError('Could not remove that device. Please try again.')
    }
  }

  const displayName = user?.email ? formatDisplayName(user.email) : ''
  const initials = user?.email ? user.email[0].toUpperCase() : '?'

  const handleSaveChanges = async () => {
    if (!profile) return
    setSaving(true)
    setSaveError(null)
    try {
      await updateProfile({
        location_preference: locationPref,
        emergency_contact_name: trimOrNull(contactName),
        emergency_contact_phone: trimOrNull(contactPhone),
        auto_alert_opt_in: autoAlertOptIn,
        allergies: trimOrNull(allergies),
        conditions: trimOrNull(conditions),
        blood_type: bloodType || null,
        medical_chat_opt_in: chatOptIn,
      })
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes.')
    } finally {
      setSaving(false)
    }
  }

  if (isMobile) {
    return (
      <div className="min-h-screen flex flex-col text-[13px]" style={{ background: '#061219', color: '#E2F1F5' }}>
        <MobileTopBar mode="browse" severity={null} onMenuOpen={() => setDrawerOpen(true)} />
        <DrawerMenu isOpen={drawerOpen} onClose={() => setDrawerOpen(false)} />

        <div
          className="mx-auto flex flex-col gap-5 w-full"
          style={{
            maxWidth: undefined,
            padding: '24px 16px 120px',
            marginTop: 56,
          }}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-4">
              <div
                className="rounded-full flex items-center justify-center flex-none"
                style={{ width: 64, height: 64, background: '#35A7C4', color: '#061219', fontWeight: 700, fontSize: 22 }}
              >
                {initials}
              </div>
              <div>
                <p className="text-[16px] font-bold" style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}>
                  {displayName}
                </p>
                <p className="text-[12px] mt-0.5" style={{ color: '#85A4B1', fontFamily: 'var(--font-sans)' }}>
                  {user?.email ?? ''}
                </p>
                <span
                  className="inline-block mt-2 text-[9px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full"
                  style={{ background: 'rgba(72, 246, 193, 0.1)', color: '#48F6C1', fontFamily: 'var(--font-mono)' }}
                >
                  Privacy protected
                </span>
              </div>
            </div>
            <span
              className="text-[9px] font-bold uppercase tracking-wide px-2.5 py-1 rounded-full flex-none"
              style={{ background: 'rgba(28, 70, 89, 0.5)', color: '#85A4B1', fontFamily: 'var(--font-mono)' }}
            >
              Member since May 2024
            </span>
          </div>

          <SectionCard title="Location preference">
            <div className="flex flex-col gap-2">
              <RadioCard
                title="Always allow"
                description="We'll use your saved location each time."
                selected={locationPref === 'always'}
                onSelect={() => setLocationPref('always')}
              />
              <RadioCard
                title="Ask each time"
                description="You'll be prompted when you start a session."
                selected={locationPref === 'ask'}
                onSelect={() => setLocationPref('ask')}
              />
            </div>
          </SectionCard>

          <SectionCard title="Preferred facility">
            <p className="text-[12px] leading-snug" style={{ color: '#85A4B1', fontFamily: 'var(--font-sans)' }}>
              Your default choice for everyday or over-the-counter care — used when we don't have a closer match from
              your location.
            </p>
            <div
              className="flex items-center justify-between px-4 py-3 rounded-xl"
              style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
            >
              <div>
                <p className="text-[13px] font-semibold" style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}>
                  St. Michael's Hospital
                </p>
                <p className="text-[11px] mt-0.5" style={{ color: '#85A4B1', fontFamily: 'var(--font-sans)' }}>
                  30 Bond St, Toronto, ON
                </p>
              </div>
              <button
                type="button"
                className="text-[11px] font-semibold flex-none"
                style={{ color: '#48F6C1', fontFamily: 'var(--font-sans)' }}
              >
                Get directions
              </button>
            </div>
          </SectionCard>

          <SectionCard title="Push notifications">
            <ToggleRow
              label="Push notifications"
              checked={permissionState === 'granted'}
              onChange={v => v ? requestPermission() : undefined}
            />
            <div className="flex flex-col gap-2">
              {devices.map(device => (
                <div
                  key={device.subscription_id}
                  className="flex items-center justify-between px-4 py-2.5 rounded-xl"
                  style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
                >
                  <span className="text-[12px]" style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}>
                    {device.device_type} — {device.active ? 'active' : 'inactive'}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeDevice(device.subscription_id)}
                    className="text-[11px] font-semibold"
                    style={{ color: '#FF7B93', fontFamily: 'var(--font-sans)' }}
                  >
                    Remove
                  </button>
                </div>
              ))}
              {devices.length === 0 && (
                <p className="text-[12px]" style={{ color: '#85A4B1', fontFamily: 'var(--font-sans)' }}>
                  No devices registered.
                </p>
              )}
              {permissionState !== 'granted' && (
                <button
                  type="button"
                  onClick={requestPermission}
                  disabled={requesting}
                  className="flex items-center justify-center gap-1.5 text-[12px] font-semibold py-2.5 rounded-xl disabled:opacity-60"
                  style={{ border: '1px dashed rgba(28, 70, 89, 0.6)', color: '#85A4B1', fontFamily: 'var(--font-sans)' }}
                >
                  <Plus size={14} />
                  {requesting ? 'Enabling…' : 'Enable on this device'}
                </button>
              )}
            </div>
          </SectionCard>

          <SectionCard title="Emergency contact">
            <TextField label="Name" value={contactName} onChange={setContactName} placeholder="Who are they to you?" />
            <TextField
              label="Phone number"
              value={contactPhone}
              onChange={setContactPhone}
              placeholder="+1 (416) 000-0000"
              type="tel"
            />
            <ToggleRow
              label="Automatically alert this contact"
              badge="Coming soon"
              caption="In urgent situations, we'll notify your contact with your status and location."
              checked={autoAlertOptIn}
              onChange={setAutoAlertOptIn}
            />
          </SectionCard>

          <SectionCard title="Medical profile">
            <TextField label="Allergies" value={allergies} onChange={setAllergies} placeholder="e.g. Penicillin, Peanuts" />
            <TextField
              label="Pre-existing conditions"
              value={conditions}
              onChange={setConditions}
              placeholder="e.g. Type II Diabetes, Hypertension"
            />
            <SelectField label="Blood type" value={bloodType} onChange={setBloodType} options={BLOOD_TYPE_OPTIONS} placeholder="Select type" />
            <ToggleRow
              {...AI_ASSISTANT_OPT_IN_COPY}
              checked={chatOptIn}
              onChange={setChatOptIn}
            />
          </SectionCard>
        </div>

        <div
          className="fixed bottom-0 left-0 right-0 flex flex-col items-center gap-2"
          style={{
            background: 'rgba(6, 18, 25, 0.95)',
            backdropFilter: 'blur(16px)',
            borderTop: '1px solid rgba(28, 70, 89, 0.4)',
            padding: 16,
            zIndex: 50,
          }}
        >
          <button
            type="button"
            onClick={handleSaveChanges}
            disabled={saving || !profile}
            className="w-full font-bold rounded-xl transition-all disabled:opacity-60"
            style={{ background: '#48F6C1', color: '#061219', padding: '12px 0', minHeight: 44 }}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          {saveError && (
            <p className="text-[11px] text-center" style={{ color: '#FF7B93' }}>{saveError}</p>
          )}
          <button
            type="button"
            className="text-[11px] font-semibold"
            style={{ color: '#FF7B93', fontFamily: 'var(--font-sans)' }}
          >
            Delete my account
          </button>
        </div>
      </div>
    )
  }

  // Web Layout Rendering
  return (
    <div className="min-h-screen flex flex-col text-[13px] overflow-hidden select-none" style={{ background: '#061219', color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}>
      {/* Top Nav Bar */}
      <header
        className="fixed top-0 left-0 right-0 h-16 flex items-center justify-between px-6 z-30"
        style={{ background: '#061219', borderBottom: '1px solid rgba(28, 70, 89, 0.4)' }}
      >
        <div className="flex items-center gap-4">
          <span className="text-[18px] font-bold tracking-wide" style={{ color: '#E2F1F5' }}>
            MediCoord<span style={{ color: '#48F6C1' }}>AI</span>
          </span>
        </div>
        <nav className="flex items-center gap-8">
          <Link
            to="/app"
            className="text-[11px] font-bold tracking-wider uppercase no-underline transition-colors hover:text-[#E2F1F5]"
            style={{ color: '#85A4B1' }}
          >
            AI Assistant
          </Link>
          <span
            className="text-[11px] font-bold tracking-wider uppercase cursor-default border-b-2 pb-5 mt-5"
            style={{ color: '#E2F1F5', borderColor: '#48F6C1' }}
          >
            Profile
          </span>
          <Link
            to="#"
            className="text-[11px] font-bold tracking-wider uppercase no-underline transition-colors hover:text-[#E2F1F5]"
            style={{ color: '#85A4B1' }}
          >
            Health Data
          </Link>
        </nav>
      </header>

      {/* Main Body */}
      <div className="flex flex-1 pt-16">
        {/* Left Sidebar */}
        <aside
          className="fixed top-16 left-0 bottom-20 w-64 flex flex-col z-20"
          style={{ background: '#061219', borderRight: '1px solid rgba(28, 70, 89, 0.4)' }}
        >
          {/* User Profile Info */}
          <div className="flex items-center gap-3 p-6" style={{ borderBottom: '1px solid rgba(28, 70, 89, 0.2)' }}>
            <div
              className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-[14px] flex-none"
              style={{ background: '#132E3C', color: '#E2F1F5' }}
            >
              {initials}
            </div>
            <div className="overflow-hidden">
              <p className="font-bold text-[13px] truncate" style={{ color: '#E2F1F5' }}>
                {displayName}
              </p>
              <p className="text-[11px] truncate mt-0.5" style={{ color: '#85A4B1' }}>
                {user?.email ?? ''}
              </p>
            </div>
          </div>

          {/* Navigation Links */}
          <div className="flex flex-col gap-1 p-4">
            <div
              className="flex items-center gap-3 px-4 py-3 rounded-xl cursor-default"
              style={{ background: '#48F6C1', color: '#061219' }}
            >
              <User size={18} />
              <span className="font-bold text-[13px]">My profile</span>
            </div>
            <Link
              to="/"
              className="flex items-center gap-3 px-4 py-3 rounded-xl no-underline mt-4 transition-colors hover:bg-[rgba(19,46,60,0.3)]"
              style={{ color: '#FF7B93' }}
            >
              <SignOut size={18} />
              <span className="font-medium text-[13px]">Sign out</span>
            </Link>
          </div>
        </aside>

        {/* Content Area */}
        <main className="ml-64 flex-1 p-10 pb-36 h-[calc(100vh-64px)] overflow-y-auto" style={{ background: '#061219' }}>
          <div className="mx-auto max-w-[1200px] flex flex-col gap-6">
            {/* Header Panel */}
            <div
              className="relative flex items-center justify-between p-6 overflow-hidden"
              style={{
                background: 'rgba(10, 29, 39, 0.8)',
                border: '1px solid rgba(28, 70, 89, 0.4)',
                borderRadius: 20,
                backdropFilter: 'blur(12px)',
              }}
            >
              {/* Glowing gradient element */}
              <div
                className="absolute left-[-20px] top-[-20px] w-48 h-48 rounded-full filter blur-[60px] opacity-20 pointer-events-none"
                style={{ background: 'radial-gradient(circle, #48F6C1 0%, transparent 70%)' }}
              />

              <div className="flex items-center gap-6 relative z-10">
                <div
                  className="w-20 h-20 rounded-full flex items-center justify-center font-bold text-[28px] flex-none"
                  style={{ background: '#48F6C1', color: '#061219' }}
                >
                  {initials}
                </div>
                <div className="flex flex-col gap-1.5">
                  <h1 className="text-[22px] font-bold" style={{ color: '#E2F1F5' }}>
                    {displayName}
                  </h1>
                  <p className="text-[13px]" style={{ color: '#85A4B1' }}>
                    {user?.email ?? ''}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className="flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full border"
                      style={{ background: 'rgba(19, 46, 60, 0.4)', borderColor: 'rgba(28, 70, 89, 0.5)', color: '#E2F1F5' }}
                    >
                      <ShieldCheck size={12} style={{ color: '#48F6C1' }} />
                      Privacy Active
                    </span>
                  </div>
                </div>
              </div>

              <div
                className="px-3 py-1.5 rounded-lg flex-none"
                style={{ background: 'rgba(19, 46, 60, 0.5)', border: '1px solid rgba(28, 70, 89, 0.3)' }}
              >
                <span className="text-[9px] font-bold tracking-wider uppercase" style={{ color: '#85A4B1', fontFamily: 'var(--font-mono)' }}>
                  MEMBER SINCE 2022
                </span>
              </div>
            </div>

            {/* 2-Column Grid, all cards sharing the same min-height */}
            <div className="grid grid-cols-2 gap-6 items-start">
              {/* Location Preference Card */}
              <div
                className="p-6 w-full flex flex-col gap-4"
                style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, minHeight: 360 }}
              >
                <div className="flex items-center gap-2">
                  <MapPin size={18} style={{ color: '#48F6C1' }} />
                  <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5' }}>
                    Location preference
                  </h2>
                </div>
                <div className="flex flex-col gap-2">
                  <RadioCard
                    title="Always allow"
                    description="We'll use your saved location each time."
                    selected={locationPref === 'always'}
                    onSelect={() => setLocationPref('always')}
                  />
                  <RadioCard
                    title="Ask each time"
                    description="You'll be prompted when you start a session."
                    selected={locationPref === 'ask'}
                    onSelect={() => setLocationPref('ask')}
                  />
                </div>
              </div>

              {/* Local Care Center Card */}
              <div
                className="p-6 w-full flex flex-col gap-4"
                style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, minHeight: 360 }}
              >
                <div className="flex items-center gap-2">
                  <Compass size={18} style={{ color: '#48F6C1' }} />
                  <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5' }}>
                    Local Care Center
                  </h2>
                </div>
                
                <div className="relative rounded-xl overflow-hidden" style={{ height: 160, border: '1px solid rgba(28, 70, 89, 0.3)' }}>
                  <MapContainer
                    center={MOUNT_SINAI_POS}
                    zoom={14}
                    scrollWheelZoom={false}
                    zoomControl={false}
                    dragging={false}
                    style={{ height: '100%', width: '100%' }}
                  >
                    <TileLayer
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                      url={cartoTileUrl('dark_all')}
                      tileSize={512}
                      zoomOffset={-1}
                      detectRetina={true}
                    />
                    <Marker position={MOUNT_SINAI_POS} icon={miniMapPinIcon} />
                  </MapContainer>
                  <div
                    className="absolute bottom-3 left-3 flex items-center gap-1.5 px-3 py-1.5 rounded-lg"
                    style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.5)', backdropFilter: 'blur(8px)', zIndex: 1000 }}
                  >
                    <span className="w-2 h-2 rounded-full" style={{ background: '#48F6C1' }} />
                    <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#E2F1F5', fontFamily: 'var(--font-mono)' }}>
                      CURRENT: MOUNT SINAI HOSPITAL
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <span className="text-[12px]" style={{ color: '#85A4B1' }}>
                    200 University Ave, Toronto, ON M5G 1X5
                  </span>
                  <a
                    href="https://maps.google.com/?q=Mount+Sinai+Hospital+Toronto"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-[12px] font-semibold no-underline transition-colors hover:text-[#48F6C1] self-start"
                    style={{ color: '#35A7C4' }}
                  >
                    Get Directions
                    <ArrowSquareOut size={14} />
                  </a>
                </div>
              </div>

              {/* Device Connectivity Card */}
              <div
                className="p-6 w-full flex flex-col gap-4"
                style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, minHeight: 360 }}
              >
                <div className="flex items-center gap-2">
                  <Watch size={18} style={{ color: '#48F6C1' }} />
                  <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5' }}>
                    Device Connectivity
                  </h2>
                </div>

                <div className="flex flex-col gap-2">
                  {devices.map(device => (
                    <div
                      key={device.subscription_id}
                      className="flex items-center justify-between p-3.5 rounded-xl"
                      style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
                    >
                      <div className="flex items-center gap-3">
                        <DeviceMobile size={20} style={{ color: '#85A4B1' }} />
                        <p className="font-bold text-[13px]" style={{ color: '#E2F1F5' }}>
                          {device.device_type} — {device.active ? 'active' : 'inactive'}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeDevice(device.subscription_id)}
                        className="text-[11px] font-semibold flex-none"
                        style={{ color: '#FF7B93', fontFamily: 'var(--font-sans)' }}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  {devices.length === 0 && (
                    <p className="text-[12px]" style={{ color: '#85A4B1' }}>
                      No devices registered.
                    </p>
                  )}
                </div>

                {permissionState !== 'granted' && (
                  <button
                    type="button"
                    onClick={requestPermission}
                    disabled={requesting}
                    className="flex items-center justify-center gap-1.5 text-[12px] font-semibold py-2.5 rounded-xl disabled:opacity-60"
                    style={{ border: '1px dashed rgba(28, 70, 89, 0.6)', color: '#85A4B1', fontFamily: 'var(--font-sans)' }}
                  >
                    <Plus size={14} />
                    {requesting ? 'Enabling…' : 'Enable on this device'}
                  </button>
                )}
              </div>

              {/* Emergency Contact Card */}
              <div
                className="p-6 w-full flex flex-col gap-4"
                style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, minHeight: 360 }}
              >
                <div className="flex items-center gap-2">
                  <Phone size={18} style={{ color: '#48F6C1' }} />
                  <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5' }}>
                    Emergency Contact
                  </h2>
                </div>

                <div
                  className="flex items-center gap-4 p-4 rounded-xl"
                  style={{ background: 'rgba(255, 123, 147, 0.08)', border: '1px solid rgba(255, 123, 147, 0.2)' }}
                >
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center flex-none"
                    style={{ background: 'rgba(255, 123, 147, 0.2)', color: '#FF7B93' }}
                  >
                    <Phone size={18} />
                  </div>
                  <div>
                    <p className="font-bold text-[13px]" style={{ color: '#E2F1F5' }}>
                      {contactName}
                    </p>
                    <p className="text-[12px] mt-0.5" style={{ color: '#85A4B1' }}>
                      {contactPhone}
                    </p>
                  </div>
                </div>

                <ToggleRow
                  label="Automatically alert this contact"
                  badge="Coming soon"
                  caption="In urgent situations, we'll notify your contact with your status and location."
                  checked={autoAlertOptIn}
                  onChange={setAutoAlertOptIn}
                />

                <button
                  type="button"
                  className="w-full py-2.5 rounded-xl font-bold transition-all border text-[12px]"
                  style={{
                    borderColor: 'rgba(28, 70, 89, 0.6)',
                    background: 'transparent',
                    color: '#E2F1F5',
                    minHeight: 38,
                  }}
                >
                  Update Contact Details
                </button>
              </div>

              {/* Medical Profile Card */}
              <div
                className="p-6 w-full flex flex-col gap-4 col-span-2"
                style={{ background: '#0A1D27', border: '1px solid rgba(28, 70, 89, 0.4)', borderRadius: 16, minHeight: 360 }}
              >
                <div className="flex items-center gap-2">
                  <Folder size={18} style={{ color: '#48F6C1' }} />
                  <h2 className="text-[14px] font-bold" style={{ color: '#E2F1F5' }}>
                    Medical Profile
                  </h2>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {/* Blood Type Box */}
                  <div
                    className="p-4 rounded-xl flex flex-col gap-1.5"
                    style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
                  >
                    <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#85A4B1', fontFamily: 'var(--font-mono)' }}>
                      BLOOD TYPE
                    </span>
                    <span className="text-[18px] font-bold" style={{ color: '#E2F1F5' }}>
                      {bloodType || 'Not set'}
                    </span>
                  </div>

                  {/* Allergies Box */}
                  <div
                    className="p-4 rounded-xl flex flex-col gap-1.5"
                    style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
                  >
                    <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#85A4B1', fontFamily: 'var(--font-mono)' }}>
                      ALLERGIES
                    </span>
                    <span className="text-[18px] font-bold" style={{ color: '#FF7B93' }}>
                      {allergies || 'None reported'}
                    </span>
                  </div>
                </div>

                {/* Pre-existing Conditions Box */}
                <div
                  className="p-4 rounded-xl flex flex-col gap-1.5"
                  style={{ background: 'rgba(19, 46, 60, 0.3)', border: '1px solid rgba(28, 70, 89, 0.4)' }}
                >
                  <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#85A4B1', fontFamily: 'var(--font-mono)' }}>
                    PRE-EXISTING CONDITIONS
                  </span>
                  <span className="text-[16px] font-bold" style={{ color: '#E2F1F5' }}>
                    {conditions || 'None reported'}
                  </span>
                </div>

                <ToggleRow
                  {...AI_ASSISTANT_OPT_IN_COPY}
                  checked={chatOptIn}
                  onChange={setChatOptIn}
                />
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Sticky Bottom Footer */}
      <footer
        className="fixed bottom-0 left-0 right-0 h-20 px-8 flex items-center justify-between z-30"
        style={{
          background: '#091821',
          borderTop: '1px solid rgba(28, 70, 89, 0.4)',
        }}
      >
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: '#FF7B93', fontFamily: 'var(--font-mono)' }}>
            UNSAVED CHANGES DETECTED
          </span>
          <span className="text-[12px]" style={{ color: '#85A4B1' }}>
            Patient User Profile (Last synced 2m ago)
          </span>
        </div>

        <div className="flex items-center gap-4">
          <button
            type="button"
            className="text-[12px] font-semibold px-4 py-2.5 rounded-xl transition-all"
            style={{ color: '#FF7B93', border: '1px solid rgba(255, 123, 147, 0.25)', background: 'transparent' }}
          >
            Delete my account
          </button>
          <button
            type="button"
            onClick={() => { if (profile) { setLocationPref(profile.location_preference); setContactName(profile.emergency_contact_name ?? ''); setContactPhone(profile.emergency_contact_phone ?? ''); setAutoAlertOptIn(profile.auto_alert_opt_in); setAllergies(profile.allergies ?? ''); setConditions(profile.conditions ?? ''); setBloodType(profile.blood_type ?? ''); setChatOptIn(profile.medical_chat_opt_in) } }}
            className="text-[12px] font-semibold px-5 py-2.5 rounded-xl border transition-colors hover:bg-[rgba(28,70,89,0.2)]"
            style={{ borderColor: 'rgba(28, 70, 89, 0.6)', color: '#E2F1F5', background: 'transparent' }}
          >
            Cancel changes
          </button>
          <button
            type="button"
            onClick={handleSaveChanges}
            disabled={saving || !profile}
            className="text-[12px] font-bold px-6 py-2.5 rounded-xl transition-all hover:opacity-90 disabled:opacity-60"
            style={{ background: '#48F6C1', color: '#061219' }}
          >
            {saving ? 'Saving…' : 'Update Me'}
          </button>
        </div>
      </footer>
    </div>
  )
}
