import { useCallback, useEffect, useMemo, useState } from 'react';
import Form4Warning from '../components/Form4Warning';
import { fetchJsonWithAuth } from '../utils/api';

const formatNumber = (value, decimals = 3) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(decimals) : '-';
};

const ArtifactStatus = ({ name, ready }) => (
  <div className="flex items-center justify-between gap-4 rounded-lg bg-[#f1f4f3] px-4 py-3 border border-[#c5c6cd]/20">
    <div className="flex items-center gap-3">
      <span className={`w-2 h-2 rounded-full ${ready ? 'bg-[#006d37]' : 'bg-[#ba1a1a]'}`}></span>
      <span className="text-sm font-bold text-[#1b263b] capitalize">{name.replaceAll('_', ' ')}</span>
    </div>
    <span className={`text-[10px] font-black uppercase tracking-widest ${ready ? 'text-[#006d37]' : 'text-[#ba1a1a]'}`}>
      {ready ? 'Ready' : 'Missing'}
    </span>
  </div>
);

export default function Settings() {
  const [summary, setSummary] = useState(null);
  const [thresholdState, setThresholdState] = useState(null);
  const [thresholdDraft, setThresholdDraft] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      const [summaryPayload, thresholdPayload] = await Promise.all([
        fetchJsonWithAuth('/api/dashboard/summary'),
        fetchJsonWithAuth('/api/settings/threshold'),
      ]);
      setSummary(summaryPayload);
      setThresholdState(thresholdPayload);
      setThresholdDraft(String(thresholdPayload.threshold ?? ''));
      setReason(thresholdPayload.reason || '');
      setError(null);
    } catch (err) {
      setError(err.status === 403 ? 'Admin access is required to edit runtime threshold settings.' : err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(loadSettings, 0);
    return () => window.clearTimeout(timer);
  }, [loadSettings]);

  const artifacts = useMemo(
    () => Object.entries(summary?.artifact_status || {}).filter(([, value]) => typeof value === 'boolean'),
    [summary],
  );

  const saveThreshold = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = await fetchJsonWithAuth('/api/settings/threshold', {
        method: 'PATCH',
        body: JSON.stringify({ threshold: Number(thresholdDraft), reason }),
      });
      setThresholdState(payload);
      setSummary((current) => current ? { ...current, threshold: payload.threshold, threshold_policy: payload.threshold_policy, threshold_source: payload.threshold_source } : current);
      setSuccess('Runtime threshold override saved and audited.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const resetThreshold = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = await fetchJsonWithAuth('/api/settings/threshold', { method: 'DELETE' });
      setThresholdState(payload);
      setThresholdDraft(String(payload.threshold ?? ''));
      setReason('');
      setSummary((current) => current ? { ...current, threshold: payload.threshold, threshold_policy: payload.threshold_policy, threshold_source: payload.threshold_source } : current);
      setSuccess('Runtime override reset to artifact baseline.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-container space-y-6">
      <div className="flex flex-col md:flex-row md:justify-between md:items-end gap-4">
        <div>
          <h1 className="heading-primary text-3xl">Settings</h1>
          <p className="text-subtitle mt-2 max-w-2xl">
            Runtime threshold configuration and read-only Form 4 administration status.
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-[#ffdad6] border border-[#ba1a1a]/20 text-[#ba1a1a] rounded-lg px-4 py-3 text-sm font-bold mb-6">
          Settings unavailable: {error}
        </div>
      )}
      {success && (
        <div className="bg-[#e8f5e9] border border-[#006d37]/20 text-[#006d37] rounded-lg px-4 py-3 text-sm font-bold mb-6">
          {success}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        <section className="panel-card col-span-12 lg:col-span-8">
          <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 mb-6">
            <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-[#1b263b] bg-[#f1f4f3] p-2 rounded-lg">
              psychology
            </span>
            <div>
              <h3 className="heading-secondary">Runtime Threshold</h3>
              <p className="text-subtitle font-medium">
                Effective anomaly threshold used by future predictions.
              </p>
            </div>
            </div>
            <span className={`inline-flex w-fit items-center rounded-md px-3 py-2 text-[10px] font-black uppercase tracking-widest ${thresholdState?.override_active ? 'bg-[#fff4ce] text-[#805600]' : 'bg-[#e8f5e9] text-[#00743a]'}`}>
              {thresholdState?.override_active ? 'Override active' : 'Artifact baseline'}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="rounded-lg bg-[#f1f4f3] p-4 border border-[#c5c6cd]/20">
              <p className="text-[10px] font-black uppercase tracking-widest text-[#45474d]">Effective Threshold</p>
              <p className="text-2xl font-black text-[#051125] mt-2">{loading ? '...' : formatNumber(thresholdState?.threshold ?? summary?.threshold)}</p>
            </div>
            <div className="rounded-lg bg-[#f1f4f3] p-4 border border-[#c5c6cd]/20">
              <p className="text-[10px] font-black uppercase tracking-widest text-[#45474d]">Artifact Baseline</p>
              <p className="text-2xl font-black text-[#051125] mt-2">{formatNumber(thresholdState?.artifact_threshold ?? summary?.artifact_threshold)}</p>
            </div>
            <div className="rounded-lg bg-[#f1f4f3] p-4 border border-[#c5c6cd]/20">
              <p className="text-[10px] font-black uppercase tracking-widest text-[#45474d]">Source</p>
              <p className="text-base font-black text-[#051125] mt-2">{thresholdState?.threshold_source || summary?.threshold_source || '-'}</p>
            </div>
            <div className="rounded-lg bg-[#f1f4f3] p-4 border border-[#c5c6cd]/20 md:col-span-3">
              <p className="text-[10px] font-black uppercase tracking-widest text-[#45474d]">Policy</p>
              <p className="text-sm font-bold text-[#051125] mt-2">
                {thresholdState?.threshold_policy || summary?.threshold_policy || 'No policy returned'}
              </p>
            </div>
          </div>

          <form onSubmit={saveThreshold} className="rounded-lg border border-[#c5c6cd]/30 bg-[#f7faf9] p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="form-label mb-2">Override Threshold</label>
                <input
                  type="number"
                  step="0.000001"
                  min="0.000001"
                  value={thresholdDraft}
                  onChange={(event) => setThresholdDraft(event.target.value)}
                  className="input-field bg-white"
                  required
                />
              </div>
              <div className="md:col-span-2">
                <label className="form-label mb-2">Audit Reason</label>
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  minLength={3}
                  className="input-field bg-white"
                  placeholder="Reason for runtime override"
                  required
                />
              </div>
            </div>
            <div className="flex flex-col sm:flex-row sm:justify-end gap-3">
              <button type="button" disabled={saving || !thresholdState?.override_active} onClick={resetThreshold} className="btn-secondary justify-center disabled:opacity-60 disabled:cursor-not-allowed">
                <span className="material-symbols-outlined text-[18px]">restart_alt</span>
                Reset to Artifact
              </button>
              <button type="submit" disabled={saving} className="btn-primary w-full sm:w-auto px-5 py-2.5 mt-0 disabled:opacity-60">
                <span className="material-symbols-outlined text-[18px]">save</span>
                Save Override
              </button>
            </div>
          </form>
        </section>

        <section className="panel-card col-span-12 lg:col-span-4 flex flex-col gap-6">
          <div>
            <h3 className="heading-secondary mb-2">Artifact Readiness</h3>
            <p className="text-subtitle leading-relaxed">
              Model, scaler, threshold, and metadata files required by latest-window inference.
            </p>
          </div>
          <div className="space-y-3">
            {loading && <div className="text-sm font-bold text-[#45474d]">Loading artifact status...</div>}
            {!loading && artifacts.length === 0 && (
              <div className="text-sm font-bold text-[#45474d]">No artifact status returned.</div>
            )}
            {artifacts.map(([name, ready]) => (
              <ArtifactStatus key={name} name={name} ready={Boolean(ready)} />
            ))}
          </div>
        </section>

        <section className="panel-card col-span-12">
          <Form4Warning className="mb-6">
            User administration is outside this implementation.
          </Form4Warning>
          <div className="flex items-center gap-3 mb-6">
            <span className="material-symbols-outlined text-[#1b263b] bg-[#f1f4f3] p-2 rounded-lg">
              group
            </span>
            <div>
              <h3 className="heading-secondary">User Access Management</h3>
              <p className="text-subtitle">Admin-only threshold routes are backend-enforced.</p>
            </div>
          </div>
          <div className="rounded-lg bg-[#f1f4f3] border border-[#c5c6cd]/20 p-6">
            <p className="text-sm font-bold text-[#1b263b]">Broad user management remains out of scope.</p>
            <p className="text-xs text-[#45474d] mt-2">
              This screen demonstrates role-gated threshold configuration, not user-list editing or key rotation.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
