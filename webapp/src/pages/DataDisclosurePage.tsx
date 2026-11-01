import { Link } from 'react-router-dom'
import { LegalPageLayout } from '../components/legal/LegalPageLayout'

export default function DataDisclosurePage() {
  const disclosureItems = [
    {
      data: 'Guest demo: random browser ID',
      badge: 'No account',
      why: 'The public demo needs no sign-in. A random ID created in your browser keeps your conversations together and counts messages for the usage limit.',
      stored: 'In your browser (local storage) and in our demo database. It is not linked to your name, email or IP address. Clearing your browser data starts a new, empty guest.',
      shared: 'Never shared.'
    },
    {
      data: 'Guest demo: chat text',
      badge: 'Deleted after 30 days',
      why: 'Shown back to you when you return in the same browser, and reviewed by the team to improve recommendations.',
      stored: 'Demo database (Railway, PostgreSQL). Each conversation and its messages are deleted 30 days after the conversation started.',
      shared: 'Sent to the language-model provider (Groq) to generate replies. Not sold or shared otherwise.'
    },
    {
      data: 'Guest demo: feedback and usage events',
      badge: 'Kept',
      why: 'Your thumbs up/down and optional comment, and three counters (conversation started, recommendation shown, route drawn), tell us whether the demo works.',
      stored: 'Demo database, linked only to the random browser ID. No IP address is stored; it is used for ten minutes, in hashed form, to limit abuse.',
      shared: 'Never shared.'
    },
    {
      data: 'Email address',
      badge: 'Account',
      why: 'Used for account creation, secure authentication, and profile identification.',
      stored: 'Supabase secure cloud database.',
      shared: 'Shared only with Supabase authentication servers.'
    },
    {
      data: 'Symptom descriptions & Triage history',
      badge: 'Sensitive',
      why: 'Used to run symptom analysis, map patient speech to clinical protocols, and save consultation logs.',
      stored: 'Supabase secure cloud database.',
      shared: 'Transmitted securely to the clinical AI language model provider; never used for model training.'
    },
    {
      data: 'Device coordinates & GPS position',
      badge: 'In-session only',
      why: 'Used solely to find nearest emergency rooms and calculate live transit times.',
      stored: 'Not stored. Used in-memory during active requests and discarded.',
      shared: 'Sent by our server to the Geoapify routing service to calculate travel times and routes.'
    },
    {
      data: 'Emergency contact metadata',
      badge: 'Optional',
      why: 'Used only if you manually request the app to generate a shared message link for family contacts.',
      stored: 'Supabase secure cloud database.',
      shared: 'Never shared with any third party; processed only by you in your browser session.'
    },
    {
      data: 'Application diagnostic logs',
      badge: 'Operational',
      why: 'Used to capture front-end rendering exceptions, software crashes, and connection failures.',
      stored: 'Sentry diagnostics registry.',
      shared: 'Shared only with Sentry monitoring servers. Content inputs are masked.'
    },
    {
      data: 'Notification device token',
      badge: 'Optional',
      why: 'Used to route real-time travel alerts and queue updates to your device.',
      stored: 'Supabase database & OneSignal registry.',
      shared: 'Registered only with OneSignal push dispatch servers.'
    },
    {
      data: 'Medical profile (allergies, conditions, blood type)',
      badge: 'Optional / Opt-in',
      why: 'Optionally provided during onboarding or in Profile. Sent to the AI triage engine only when the "Let the AI assistant use this" toggle is enabled.',
      stored: 'Supabase secure cloud database.',
      shared: 'Transmitted to the clinical AI language model only when opt-in is active. Never used for model training.'
    }
  ]

  return (
    <LegalPageLayout
      title="Data Disclosure"
      description="An itemized breakdown of every piece of data MediCoord AI collects, why it's collected, where it's stored, and who it's shared with."
      lastUpdated="October 7, 2026"
    >
      <p className="text-sm md:text-body-md text-[#85A4B1] leading-relaxed">
        MediCoord AI is built on real Canadian public health data — no simulated locations, no synthetic wait times.
        This page shows exactly what we collect, where it lives, and who can see it. For your legal rights, see our <Link to="/privacy">Privacy Policy</Link>.
      </p>

      {/* Prominent Canadian Sourcing Alert Card */}
      <div className="my-8 border border-[#48F6C1]/30 bg-[#48F6C1]/5 rounded-xl p-5 md:p-6 flex flex-col gap-3">
        <span className="text-[10px] font-mono font-bold text-[#48F6C1] uppercase tracking-widest">
          Canadian Clinical Data Integrations & Sources
        </span>
        <h3 className="text-white text-md font-bold leading-snug">
          Real Regional Telemetry Sourcing
        </h3>
        <p className="text-xs text-[#85A4B1] leading-relaxed">
          MediCoord AI relies entirely on authentic geographical and medical coordinates.
          All hospital locations, clinical resources, wait time estimations, and routing nodes are fetched directly from public Canadian sources, including:
        </p>
        <ul className="list-disc pl-5 text-xs text-[#E2F1F5] space-y-1 mt-1 font-sans">
          <li><strong>Health Ontario Directory</strong> (hospital capabilities, specialized care classifications)</li>
          <li><strong>City of Toronto Open Data Portal</strong> (emergency facilities, public medical centers)</li>
          <li><strong>Metropolitan Toronto Transit Telemetry</strong> (transit times, street routes, and traffic datasets)</li>
        </ul>
        <p className="text-xs text-[#7AA0B0] leading-relaxed italic mt-1">
          No coordinates, patient distributions, or facility parameters are simulated; they match real-world Canadian public healthcare configurations.
        </p>
      </div>

      <h2 className="text-white text-lg font-bold mt-10 mb-4 border-b border-[#1C4659]/30 pb-2">
        Data Collection Directory
      </h2>
      <p className="text-xs text-[#7AA0B0] mb-4">
        Below is the exhaustive directory of data elements processed by our application.
      </p>

      <div className="flex flex-col gap-4 my-6">
        {disclosureItems.map((item) => (
          <div key={item.data} className="border border-[#1C4659]/45 bg-[#061219]/60 rounded-xl p-5 md:p-6 flex flex-col gap-4 hover:border-[#1C4659]/80 transition-all">
            <div className="flex items-center justify-between border-b border-[#1C4659]/30 pb-2.5">
              <span className="text-sm font-bold text-white leading-snug">{item.data}</span>
              <span className="text-[9px] font-mono text-[#00D2FF] bg-[#00D2FF]/10 px-2 py-0.5 rounded border border-[#00D2FF]/20 font-bold uppercase tracking-wider">
                {item.badge}
              </span>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-mono">
              <div className="flex flex-col gap-1">
                <span className="text-[#7AA0B0] text-[9.5px] uppercase tracking-wider">Purpose:</span>
                <span className="text-[#85A4B1] font-sans text-xs leading-relaxed">{item.why}</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[#7AA0B0] text-[9.5px] uppercase tracking-wider">Storage Target:</span>
                <span className="text-white font-sans text-xs leading-relaxed">{item.stored}</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[#7AA0B0] text-[9.5px] uppercase tracking-wider">Sharing Limit:</span>
                <span className="text-white font-sans text-xs leading-relaxed">{item.shared}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <p className="text-sm md:text-body-md text-[#85A4B1] leading-relaxed mt-8">
        We do not sell any of the above metadata or telemetry, and we do not use it for commercial advertisement.
      </p>

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
              {
                "@type": "Question",
                "name": "Does MediCoord AI store my GPS location?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "No. Your device location is used in-memory during an active request to calculate travel times and is discarded immediately after. It is never stored in our database."
                }
              },
              {
                "@type": "Question",
                "name": "Can MediCoord AI see my symptom descriptions?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "Your symptom descriptions are transmitted securely to an AI language model to generate the triage assessment. They are stored in your conversation history in our database but are never used to train any AI model."
                }
              },
              {
                "@type": "Question",
                "name": "Who can see my MediCoord AI data?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "Only you and our service backend can access your records. Data is shared only with the service providers that make the app work: Supabase for storage, Sentry for error tracking, OneSignal for push notifications, and the AI provider for symptom triage."
                }
              },
              {
                "@type": "Question",
                "name": "Is my emergency contact shared with anyone?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "No. Emergency contact metadata is never shared with any third party. It is processed only by you in your browser session when you choose to generate a message link."
                }
              },
              {
                "@type": "Question",
                "name": "Does MediCoord AI sell my data?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "No. MediCoord AI does not sell any data and does not use it for commercial advertisement."
                }
              }
            ]
          })
        }}
      />
    </LegalPageLayout>
  )
}
