import { useState } from 'react';
import { useGeolocation } from '../hooks/useGeolocation';

const GEO_ERROR_CODES: Record<number, string> = {
  1: 'PERMISSION_DENIED',
  2: 'POSITION_UNAVAILABLE',
  3: 'TIMEOUT',
}

export default function TestLocationPage() {
  const { coords, requesting, denied, lastError, requestOnce } = useGeolocation();
  const [debugLogs, setDebugLogs] = useState<string[]>([]);

  const addLog = (msg: string) => {
    setDebugLogs(prev => [...prev, `${new Date().toISOString()} - ${msg}`]);
  };

  const handleRequest = async () => {
    addLog('Button clicked. Calling requestOnce()...');

    if (!navigator.geolocation) {
      addLog('FAIL: navigator.geolocation is undefined — page must be served over HTTPS');
      return;
    }

    try {
      const result = await requestOnce();
      addLog(`requestOnce() returned: ${JSON.stringify(result)}`);

      if (!result) {
        // window.lastGeoError is set synchronously before resolve(null) — safe to read here
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const raw = (window as any).lastGeoError;
        if (raw) {
          const label = GEO_ERROR_CODES[raw.code] ?? `UNKNOWN(${raw.code})`;
          addLog(`Geolocation error — ${label}: ${raw.message}`);
        } else {
          addLog('Returned null with no error object (geolocation may be unavailable)');
        }
      }
    } catch (err) {
      addLog(`Exception: ${String(err)}`);
    }
  };

  return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif', maxWidth: '600px', margin: '0 auto' }}>
      <h1>iOS Geolocation Test Page</h1>
      <p style={{ marginBottom: '20px', color: '#555' }}>
        Make sure you access this page using your local IP address (e.g., http://192.168.x.x:5173/testlocation) 
        and note that iOS Safari requires HTTPS for geolocation in many cases, though localhost is an exception. 
        If you are testing from an external device on the network, you might need a local tunnel (like ngrok) to provide HTTPS.
      </p>
      
      <button 
        onClick={handleRequest} 
        disabled={requesting}
        style={{
          padding: '12px 24px',
          fontSize: '18px',
          background: '#007BFF',
          color: 'white',
          border: 'none',
          borderRadius: '8px',
          cursor: requesting ? 'not-allowed' : 'pointer',
          width: '100%'
        }}
      >
        {requesting ? 'Requesting Location...' : 'Get My Location'}
      </button>

      <div style={{ marginTop: '30px', padding: '15px', background: '#f8f9fa', borderRadius: '8px' }}>
        <h2>State Status</h2>
        <p><strong>Requesting:</strong> {requesting.toString()}</p>
        <p><strong>Denied:</strong> {denied.toString()}</p>
        
        <h2>Coordinates</h2>
        {coords ? (
          <div style={{ background: '#d4edda', padding: '10px', borderRadius: '5px', color: '#155724' }}>
            <p><strong>Latitude:</strong> {coords.lat}</p>
            <p><strong>Longitude:</strong> {coords.lng}</p>
          </div>
        ) : (
          <p>No coordinates available yet.</p>
        )}

        {lastError && (
          <div style={{ marginTop: '20px', background: '#f8d7da', padding: '10px', borderRadius: '5px', color: '#721c24' }}>
            <h3>Geolocation Error</h3>
            <p><strong>Code {lastError.code}:</strong> {GEO_ERROR_CODES[lastError.code] ?? 'UNKNOWN'}</p>
            <p>{lastError.message}</p>
          </div>
        )}
      </div>

      <div style={{ marginTop: '30px', borderTop: '1px solid #ccc', paddingTop: '20px' }}>
        <h2>Debug Logs</h2>
        <div style={{ background: '#333', color: '#0f0', padding: '10px', borderRadius: '5px', height: '200px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '12px' }}>
          {debugLogs.length === 0 ? 'No logs yet.' : debugLogs.map((log, i) => (
            <div key={i}>{log}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
