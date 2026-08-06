import { Link } from 'react-router-dom';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts';
import Form4Warning from '../components/Form4Warning';
import { fetchJsonWithAuth } from '../utils/api';

const FALLBACK_CURRENT = [4.8, 5.0, 4.6, 5.2, 4.9, 5.8, 6.4, 6.0, 6.2, 5.8, 6.1, 5.7, 6.6, 6.0, 6.3, 5.9, 6.7, 6.1, 6.4, 5.9, 6.2];
const FALLBACK_VIBRATION = [0.22, 0.36, 0.28, 0.42, 0.31, 0.48, 0.35, 0.46, 0.33, 0.51, 0.38, 0.49, 0.41, 0.55, 0.43, 0.58, 0.44, 0.52, 0.40, 0.47];

const toNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatNumber = (value, decimals = 3) => {
  const parsed = toNumber(value);
  return parsed === null ? '-' : parsed.toFixed(decimals);
};

const formatTime = (timestamp) => {
  if (!timestamp) return 'No telemetry yet';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return 'Invalid timestamp';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatDateTick = (timestamp) => {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${day}/${month} ${hours}:${minutes}`;
};

const formatFullDateTime = (timestamp) => {
  if (!timestamp) return 'No timestamp';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return 'Invalid timestamp';
  return (
    date.toLocaleString('id-ID', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }) + ' WIB'
  );
};

const statusStyle = {
  HEALTHY: {
    bg: 'bg-[#6bfe9c]',
    text: 'text-[#00743a]',
    icon: 'check_circle',
    label: 'HEALTHY',
  },
  WARNING: {
    bg: 'bg-[#ffe08a]',
    text: 'text-[#805600]',
    icon: 'warning',
    label: 'WARNING',
  },
  CRITICAL: {
    bg: 'bg-[#ffdad6]',
    text: 'text-[#ba1a1a]',
    icon: 'report',
    label: 'CRITICAL',
  },
  'NO DATA': {
    bg: 'bg-[#e0e3e2]',
    text: 'text-[#45474d]',
    icon: 'pending',
    label: 'NO DATA',
  },
};

const Dashboard = () => {
  const [summary, setSummary] = useState(null);
  const [telemetry, setTelemetry] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [inferenceState, setInferenceState] = useState({
    loading: false,
    result: null,
    error: null,
    status: null,
    lastRunAt: null,
  });
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);

  const loadDashboard = useCallback(async ({ showLoading = true } = {}) => {
    try {
      if (showLoading) {
        setLoading(true);
      }
      const [summaryPayload, telemetryPayload] = await Promise.all([
        fetchJsonWithAuth('/api/dashboard/summary'),
        fetchJsonWithAuth('/api/telemetry/latest?limit=1440'),
      ]);

      setSummary(summaryPayload);
      setTelemetry(Array.isArray(telemetryPayload) ? [...telemetryPayload].reverse() : []);
      setLastRefreshedAt(new Date());
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    const timer = window.setInterval(() => loadDashboard({ showLoading: false }), 60000);

    return () => window.clearInterval(timer);
  }, [loadDashboard]);

  const handleRunLatestInference = async () => {
    setInferenceState((previous) => ({ ...previous, loading: true, error: null, status: null }));
    try {
      const result = await fetchJsonWithAuth(
        '/api/predict/anomaly/latest?machine_id=PMA%20Granulator%20%2301',
        { method: 'POST' },
      );
      setInferenceState({ loading: false, result, error: null, status: null, lastRunAt: new Date() });
      await loadDashboard({ showLoading: false });
    } catch (err) {
      setInferenceState((previous) => ({
        ...previous,
        loading: false,
        error: err.message,
        status: err.status || null,
        lastRunAt: new Date(),
      }));
    }
  };

  const telemetryCurrentValues = useMemo(
    () => telemetry.map((row) => toNumber(row.impeller_ampere)).filter((value) => value !== null),
    [telemetry],
  );
  const currentUsesFallback = telemetryCurrentValues.length === 0;

  const currentChartData = useMemo(() => {
    if (!telemetry.length) {
      return FALLBACK_CURRENT.map((val, idx) => ({
        timestampLabel: `Point ${idx + 1}`,
        fullTime: `Fallback Point ${idx + 1}`,
        actualCurrent: val,
        baselineCurrent: val,
      }));
    }

    const rawSeries = telemetry.map((row) => {
      const actual = toNumber(row.impeller_ampere);
      return {
        timestampLabel: formatDateTick(row.timestamp),
        fullTime: formatFullDateTime(row.timestamp),
        actualCurrent: actual !== null ? Number(actual.toFixed(2)) : null,
      };
    });

    return rawSeries.map((item, idx, arr) => {
      const start = Math.max(0, idx - 4);
      const windowSlice = arr.slice(start, idx + 1).map((d) => d.actualCurrent).filter((v) => v !== null);
      const baseline = windowSlice.length
        ? windowSlice.reduce((sum, v) => sum + v, 0) / windowSlice.length
        : item.actualCurrent;
      return {
        ...item,
        baselineCurrent: baseline !== null ? Number(baseline.toFixed(2)) : null,
      };
    });
  }, [telemetry]);

  const vibrationSensorValues = useMemo(() => {
    return telemetry
      .map((row) => {
        const x = toNumber(row.x_axis_peak_acceleration);
        const z = toNumber(row.z_axis_peak_acceleration);
        if (x === null && z === null) return null;
        return ((x || 0) + (z || 0)) / (x !== null && z !== null ? 2 : 1);
      })
      .filter((value) => value !== null);
  }, [telemetry]);
  const vibrationUsesFallback = vibrationSensorValues.length === 0;

  const vibrationChartData = useMemo(() => {
    if (!telemetry.length) {
      return FALLBACK_VIBRATION.map((val, idx) => ({
        timestampLabel: `Point ${idx + 1}`,
        fullTime: `Fallback Point ${idx + 1}`,
        xPeak: val,
        zPeak: val,
      }));
    }

    return telemetry.map((row) => {
      const x = toNumber(row.x_axis_peak_acceleration);
      const z = toNumber(row.z_axis_peak_acceleration);
      return {
        timestampLabel: formatDateTick(row.timestamp),
        fullTime: formatFullDateTime(row.timestamp),
        xPeak: x !== null ? Number(x.toFixed(3)) : null,
        zPeak: z !== null ? Number(z.toFixed(3)) : null,
      };
    });
  }, [telemetry]);

  const latestReading = summary?.latest_reading || telemetry[telemetry.length - 1] || null;
  const latestPrediction = summary?.latest_prediction || null;
  const threshold = toNumber(summary?.threshold);
  const anomalyScore = toNumber(latestPrediction?.reconstruction_error);
  const status = summary?.status || 'NO DATA';
  const statusConfig = statusStyle[status] || statusStyle['NO DATA'];
  const statusDot =
    status === 'CRITICAL'
      ? 'bg-[#ba1a1a]'
      : status === 'WARNING'
        ? 'bg-[#805600]'
        : status === 'NO DATA'
          ? 'bg-[#75777d]'
          : 'bg-[#00743a]';
  const inferenceRuntimeMessage =
    inferenceState.status === 503
      ? 'ML runtime or artifacts are unavailable. Confirm Docker imports and copied model artifacts before rerunning latest-window inference.'
      : null;

  const gaugeRatio = anomalyScore !== null && threshold ? Math.min(anomalyScore / Math.max(threshold * 1.25, anomalyScore), 1) : 0.08;
  const gaugeOffset = 251.2 - 251.2 * gaugeRatio;
  const latestVibration = vibrationSensorValues.length
    ? vibrationSensorValues[vibrationSensorValues.length - 1]
    : FALLBACK_VIBRATION[FALLBACK_VIBRATION.length - 1];

  const sensorCards = [
    ['thermostat', 'Temp S-01', latestReading?.temperature_c],
    ['speed', 'RPM M-04', latestReading?.impeller_rpm],
    ['electric_bolt', 'Amp A-03', latestReading?.impeller_ampere],
    ['vibration', 'Vib V-02', latestReading?.x_axis_peak_acceleration ?? latestReading?.z_axis_peak_acceleration],
  ];

  return (
    <div className="page-container bg-[#f1f4f3] space-y-8">
      {error && (
        <div className="bg-[#ffdad6] border border-[#ba1a1a]/20 text-[#ba1a1a] rounded-lg px-4 py-3 text-sm font-bold">
          Backend data unavailable: {error}
        </div>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl p-8 flex flex-col justify-between shadow-sm relative overflow-hidden">
          <div className="relative z-10">
            <h2 className="text-4xl font-extrabold font-headline tracking-tight text-[#051125] mb-2">
              {summary?.machine_id || 'PMA Granulator #01'}
            </h2>
            <p className="text-[#45474d] font-body max-w-lg leading-relaxed">
              System monitoring the wet granulation process with LSTM Autoencoder anomaly detection. The dashboard is predictive monitoring only and does not control the machine.
            </p>
          </div>
          <div className="mt-8 flex flex-wrap gap-4 z-10">
            <button
              onClick={handleRunLatestInference}
              disabled={inferenceState.loading}
              className="px-6 py-3 bg-gradient-to-br from-[#051125] to-[#1b263b] text-white text-xs font-bold uppercase tracking-widest rounded-lg flex items-center gap-2 hover:opacity-90 active:scale-95 transition-all shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <span className={`material-symbols-outlined text-sm ${inferenceState.loading ? 'animate-spin' : ''}`}>
                {inferenceState.loading ? 'sync' : 'psychology'}
              </span>
              {inferenceState.loading ? 'Running Inference' : 'Run Latest Inference'}
            </button>
            <Link to="/app/pma" className="px-6 py-3 bg-[#e6e9e8] text-[#051125] text-xs font-bold uppercase tracking-widest rounded-lg flex items-center gap-2 hover:bg-[#e0e3e2] transition-colors">
              <span className="material-symbols-outlined text-sm">history</span>
              View PMA Data
            </Link>
            <Link
              to="/app/maintenance"
              state={{
                machineId: summary?.machine_id || 'PMA Granulator #01',
                anomalyEventId: latestPrediction?.id || null,
                prefill: latestPrediction
                  ? `Latest prediction ${latestPrediction.severity}: score ${formatNumber(latestPrediction.reconstruction_error, 3)} against threshold ${formatNumber(latestPrediction.threshold, 3)}.`
                  : 'Maintenance follow-up for PMA Granulator monitoring review.',
              }}
              className="btn-secondary px-5 py-3 justify-center"
            >
              <span className="material-symbols-outlined text-sm">medical_services</span>
              Log Ticket
            </Link>
          </div>
          <p className="mt-3 text-[11px] font-bold text-[#45474d]">
            Tickets record human review only and do not control the PMA Granulator.
          </p>
          {inferenceState.error && (
            <div className="mt-4 rounded-lg bg-[#ffdad6] px-4 py-3 text-xs font-bold text-[#ba1a1a]">
              Latest inference failed: {inferenceState.error}
              {inferenceRuntimeMessage && <p className="mt-1 text-[#7c1d18]">{inferenceRuntimeMessage}</p>}
            </div>
          )}
          {inferenceState.result && (
            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3 rounded-lg bg-[#f7faf9] border border-[#c5c6cd]/30 p-4 text-xs">
              <div>
                <p className="font-bold uppercase text-[#45474d]">Source</p>
                <p className="font-bold text-[#051125]">{inferenceState.result.source || 'latest window'}</p>
              </div>
              <div>
                <p className="font-bold uppercase text-[#45474d]">Window</p>
                <p className="font-bold text-[#051125]">
                  {formatTime(inferenceState.result.window_start)} - {formatTime(inferenceState.result.window_end)}
                </p>
              </div>
              <div>
                <p className="font-bold uppercase text-[#45474d]">Severity</p>
                <p className="font-bold text-[#051125]">{inferenceState.result.severity}</p>
              </div>
              <div>
                <p className="font-bold uppercase text-[#45474d]">MAE / Threshold</p>
                <p className="font-bold text-[#051125]">
                  {formatNumber(inferenceState.result.reconstruction_error, 3)} / {formatNumber(inferenceState.result.threshold, 3)}
                </p>
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-3 text-[11px] font-bold uppercase tracking-widest text-[#45474d]">
            <span>Last refreshed: {lastRefreshedAt ? lastRefreshedAt.toLocaleTimeString() : 'Not yet'}</span>
            <span>Last inference result: {inferenceState.lastRunAt ? inferenceState.lastRunAt.toLocaleTimeString() : 'Not run this session'}</span>
          </div>
          <div className="absolute top-0 right-0 w-64 h-full opacity-5 pointer-events-none">
            <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
              <path d="M44.7,-76.4C58.1,-69.2,69.2,-58.1,77.3,-44.7C85.4,-31.3,90.5,-15.7,89.3,-0.7C88.1,14.3,80.7,28.6,71.5,41.2C62.3,53.8,51.3,64.7,38.1,72.4C24.9,80.1,9.4,84.6,-5.6,83.1C-20.6,81.6,-35.1,74.1,-47.3,64.8C-59.5,55.5,-69.4,44.4,-76.1,31.5C-82.8,18.6,-86.3,3.9,-84.4,-10.1C-82.5,-24.1,-75.2,-37.4,-65.4,-48.5C-55.6,-59.6,-43.3,-68.5,-30.2,-75.4C-17.1,-82.3,-3.2,-87.2,11.2,-86.3C25.6,-85.4,44.7,-76.4,44.7,-76.4Z" fill="#051125" transform="translate(140 100)"></path>
            </svg>
          </div>
        </div>

        <div className={`${statusConfig.bg} rounded-xl p-8 flex flex-col items-center justify-center text-center space-y-4 shadow-md group`}>
          <div className="w-20 h-20 rounded-full bg-white/30 flex items-center justify-center animate-pulse">
            <span className={`material-symbols-outlined ${statusConfig.text} text-4xl`} style={{ fontVariationSettings: "'FILL' 1" }}>{statusConfig.icon}</span>
          </div>
          <div>
            <span className={`text-[0.6875rem] font-bold font-label uppercase tracking-widest ${statusConfig.text}`}>Current Machine Status</span>
            <h3 className={`text-5xl font-extrabold font-headline ${statusConfig.text} tracking-tighter mt-1`}>{statusConfig.label}</h3>
          </div>
          <div className="flex items-center gap-2 bg-white/30 px-4 py-1.5 rounded-full">
            <span className={`w-2 h-2 rounded-full ${statusDot}`}></span>
            <span className={`text-[10px] font-bold uppercase ${statusConfig.text}`}>{loading ? 'Syncing backend' : `Last sample ${formatTime(latestReading?.timestamp)}`}</span>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 bg-white rounded-xl p-6 shadow-sm border border-[#c5c6cd]/10">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h4 className="font-headline font-bold text-[#051125] flex items-center gap-2">
                <span className="material-symbols-outlined text-[#051125]">electric_bolt</span>
                Motor Current vs Rolling Baseline (24-Hour Stream)
              </h4>
              <p className="text-xs text-[#45474d] mt-1 font-body">
                {currentUsesFallback ? 'Fallback values shown because backend current telemetry is unavailable' : '24-hour continuous telemetry stream with anomaly threshold reference'}
              </p>
            </div>
          </div>

          <div className="h-[280px] w-full">
            {loading ? (
              <div className="flex h-full items-center justify-center text-[#45474d] text-xs font-bold uppercase tracking-widest">
                Syncing telemetry stream...
              </div>
            ) : currentChartData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-[#45474d] text-xs font-bold uppercase tracking-widest">
                No backend telemetry rows yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={currentChartData} margin={{ top: 10, right: 30, left: -10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e0e3e2" />
                  <XAxis
                    dataKey="timestampLabel"
                    stroke="#75777d"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={40}
                  />
                  <YAxis
                    stroke="#75777d"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    unit=" A"
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#051125', borderRadius: '8px', border: 'none', color: '#ffffff' }}
                    labelStyle={{ color: '#94a3b8', fontSize: '11px', fontWeight: '600' }}
                    itemStyle={{ fontSize: '12px', fontWeight: '600' }}
                    labelFormatter={(label, payload) => payload?.[0]?.payload?.fullTime || label}
                  />
                  <Legend iconType="circle" wrapperStyle={{ paddingTop: '10px', fontSize: '11px', fontWeight: 'bold' }} />
                  {threshold !== null && (
                    <ReferenceLine
                      y={threshold}
                      stroke="#ba1a1a"
                      strokeDasharray="4 4"
                      label={{ value: `Threshold: ${threshold.toFixed(3)}`, fill: '#ba1a1a', fontSize: 10, position: 'top' }}
                    />
                  )}
                  <Line
                    type="monotone"
                    dataKey="actualCurrent"
                    name="Actual Current (A)"
                    stroke="#1B263B"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="baselineCurrent"
                    name="Rolling Baseline (A)"
                    stroke="#64748b"
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 bg-white rounded-xl p-6 shadow-sm flex flex-col justify-between">
          <h4 className="font-headline font-bold text-[#051125] flex items-center gap-2 mb-6">
            <span className="material-symbols-outlined text-[#1b263b]">psychology</span>
            Anomaly Score (MAE)
          </h4>
          <div className="flex-1 flex flex-col items-center justify-center">
            <div className="relative w-48 h-48 flex items-center justify-center">
              <svg className="w-full h-full -rotate-90 transform" viewBox="0 0 100 100">
                <circle className="text-[#e0e3e2]" cx="50" cy="50" fill="transparent" r="40" stroke="currentColor" strokeWidth="8"></circle>
                <circle className={latestPrediction?.is_anomaly ? 'text-[#ba1a1a]' : 'text-[#006d37]'} cx="50" cy="50" fill="transparent" r="40" stroke="currentColor" strokeDasharray="251.2" strokeDashoffset={gaugeOffset} strokeLinecap="round" strokeWidth="8"></circle>
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-4xl font-extrabold font-headline text-[#051125]">{formatNumber(anomalyScore, 3)}</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-[#45474d]">{latestPrediction?.severity || 'No score'}</span>
              </div>
            </div>
            <p className="text-[10px] text-center text-[#45474d] mt-4 leading-relaxed">
              LSTM Autoencoder score is unsupervised anomaly detection, not a remaining-life prediction. Threshold: {threshold === null ? '-' : threshold.toFixed(3)}
            </p>
          </div>
          <div className="mt-6 pt-6 border-t border-[#c5c6cd]/10 flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase text-[#45474d]">Sensor Integrity</span>
            <div className="flex gap-1">
              {sensorCards.map((sensor) => (
                <span key={sensor[1]} className={`w-1 h-3 rounded-full ${toNumber(sensor[2]) === null ? 'bg-[#ba1a1a]' : 'bg-[#006d37]'}`}></span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 bg-white rounded-xl p-6 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-headline font-bold text-[#051125] flex items-center gap-2">
              <span className="material-symbols-outlined text-[#1b263b]">waves</span>
              Vibration Peak Acceleration (24-Hour Stream)
            </h4>
            <span className="text-xs font-bold text-[#006d37] bg-[#6bfe9c] px-3 py-1 rounded-full">
              {formatNumber(latestVibration, 2)} g
            </span>
          </div>

          <div className="h-[240px] w-full">
            {loading ? (
              <div className="flex h-full items-center justify-center text-[#45474d] text-xs font-bold uppercase tracking-widest">
                Syncing vibration stream...
              </div>
            ) : vibrationChartData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-[#45474d] text-xs font-bold uppercase tracking-widest">
                No vibration data available
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={vibrationChartData} margin={{ top: 10, right: 20, left: -10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e0e3e2" />
                  <XAxis
                    dataKey="timestampLabel"
                    stroke="#75777d"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={40}
                  />
                  <YAxis
                    stroke="#75777d"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    unit=" g"
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#051125', borderRadius: '8px', border: 'none', color: '#ffffff' }}
                    labelStyle={{ color: '#94a3b8', fontSize: '11px', fontWeight: '600' }}
                    itemStyle={{ fontSize: '12px', fontWeight: '600' }}
                    labelFormatter={(label, payload) => payload?.[0]?.payload?.fullTime || label}
                  />
                  <Legend iconType="circle" wrapperStyle={{ paddingTop: '10px', fontSize: '11px', fontWeight: 'bold' }} />
                  <Line
                    type="monotone"
                    dataKey="xPeak"
                    name="X-Peak (g)"
                    stroke="#006d37"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="zPeak"
                    name="Z-Peak (g)"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="lg:col-span-5 bg-white rounded-xl p-6 shadow-sm">
          <h4 className="font-headline font-bold text-[#051125] flex items-center gap-2 mb-6">
            <span className="material-symbols-outlined text-[#1b263b]">settings_remote</span>
            Sensor Health Status
          </h4>
          <div className="grid grid-cols-2 gap-4">
            {sensorCards.map(([icon, label, value]) => (
              <div key={label} className="p-4 rounded-lg bg-[#f1f4f3] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="material-symbols-outlined text-[#1b263b] text-lg">{icon}</span>
                  <span className="text-xs font-bold text-[#051125]">{label}</span>
                </div>
                <span className={`w-2 h-2 rounded-full ${toNumber(value) === null ? 'bg-[#ba1a1a] animate-pulse' : 'bg-[#006d37]'}`}></span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Dashboard;
