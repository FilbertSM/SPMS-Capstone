import { useState, useEffect, useCallback } from 'react';
import { fetchJsonWithAuth, fetchBlobWithAuth } from '../utils/api';

const formatDisplayDate = (dateStr) => {
  if (!dateStr) return '';
  const parts = dateStr.split('-');
  if (parts.length !== 3) return dateStr;
  const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
};

const statusStyles = {
  critical: {
    badge: 'bg-[#ffdad6] text-[#ba1a1a] border border-[#ba1a1a]/20',
    icon: 'report',
    label: 'CRITICAL',
    accent: 'border-l-[#ba1a1a]',
  },
  warning: {
    badge: 'bg-[#ffe08a] text-[#805600] border border-[#805600]/20',
    icon: 'warning',
    label: 'WARNING',
    accent: 'border-l-[#805600]',
  },
  normal: {
    badge: 'bg-[#6bfe9c]/20 text-[#00743a] border border-[#00743a]/20',
    icon: 'check_circle',
    label: 'HEALTHY',
    accent: 'border-l-[#00743a]',
  },
};

export default function DailySummary() {
  const getTodayWIB = () => {
    const now = new Date();
    const utc = now.getTime() + now.getTimezoneOffset() * 60000;
    const wib = new Date(utc + 7 * 3600000);
    return wib.toISOString().split('T')[0];
  };

  const [selectedDate, setSelectedDate] = useState(getTodayWIB());
  const [historyList, setHistoryList] = useState([]);
  const [historyFilter, setHistoryFilter] = useState('all'); // 'all' | 'issues'
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);

  const [summaryData, setSummaryData] = useState(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState(true);
  const [summaryError, setSummaryError] = useState(null);

  const [pdfBlobUrl, setPdfBlobUrl] = useState(null);
  const [isLoadingPdf, setIsLoadingPdf] = useState(false);

  // Dispatch modal
  const [isDispatchModalOpen, setIsDispatchModalOpen] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState(null);

  // 1. Load History Timeline
  const loadHistory = useCallback(async () => {
    setIsLoadingHistory(true);
    try {
      const data = await fetchJsonWithAuth('/api/alerts/daily-summary/history?limit=30');
      setHistoryList(data || []);
    } catch (err) {
      console.error('Failed to load daily history:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  // 2. Load Daily Summary & PDF for Selected Date
  const loadSummaryAndPdf = useCallback(async (targetDate) => {
    setIsLoadingSummary(true);
    setIsLoadingPdf(true);
    setSummaryError(null);

    if (pdfBlobUrl) {
      URL.revokeObjectURL(pdfBlobUrl);
      setPdfBlobUrl(null);
    }

    try {
      const summary = await fetchJsonWithAuth(`/api/alerts/daily-summary?date=${targetDate}`);
      setSummaryData(summary);
    } catch (err) {
      setSummaryError(err.message || 'Failed to load daily summary data.');
    } finally {
      setIsLoadingSummary(false);
    }

    try {
      const blob = await fetchBlobWithAuth(`/api/alerts/daily-summary/report-pdf?date=${targetDate}`);
      const url = URL.createObjectURL(blob);
      setPdfBlobUrl(url);
    } catch (err) {
      console.error('Failed to load PDF blob:', err);
    } finally {
      setIsLoadingPdf(false);
    }
  }, [pdfBlobUrl]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSummaryAndPdf(selectedDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate]);

  useEffect(() => {
    return () => {
      if (pdfBlobUrl) {
        URL.revokeObjectURL(pdfBlobUrl);
      }
    };
  }, [pdfBlobUrl]);

  // Handler: Download PDF
  const handleDownloadPdf = async () => {
    try {
      const blob = await fetchBlobWithAuth(`/api/alerts/daily-summary/report-pdf?date=${selectedDate}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `SPMS_Daily_Report_${selectedDate}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download PDF report: ' + err.message);
    }
  };

  // Handler: Print PDF
  const handlePrintPdf = () => {
    if (pdfBlobUrl) {
      const printWindow = window.open(pdfBlobUrl);
      if (printWindow) {
        printWindow.focus();
        setTimeout(() => printWindow.print(), 500);
      }
    } else {
      handleDownloadPdf();
    }
  };

  // Handler: Dispatch to Telegram
  const handleSendTelegram = async () => {
    setIsDispatching(true);
    setDispatchResult(null);
    try {
      const result = await fetchJsonWithAuth('/api/alerts/daily-summary/dispatch', {
        method: 'POST',
        body: JSON.stringify({ date: selectedDate }),
      });
      setDispatchResult({ success: true, message: result.message });
      setTimeout(() => {
        setIsDispatchModalOpen(false);
        setDispatchResult(null);
      }, 2500);
    } catch (err) {
      setDispatchResult({ success: false, message: err.message || 'Failed to dispatch summary to Telegram.' });
    } finally {
      setIsDispatching(false);
    }
  };

  const filteredHistory = historyList.filter((item) => {
    if (historyFilter === 'issues') {
      return item.status === 'warning' || item.status === 'critical';
    }
    return true;
  });

  const currentStatus = summaryData?.status || 'normal';
  const statusCfg = statusStyles[currentStatus] || statusStyles.normal;

  return (
    <div className="page-container space-y-6">
      {/* Page Header */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="heading-primary text-3xl flex items-center gap-3">
            {/* <span className="material-symbols-outlined text-3xl text-[#00743a]">summarize</span> */}
            Daily Alert Summary
          </h2>
          <p className="text-subtitle mt-1">
            Historical operational timeline and official A4 compliance maintenance reports.
          </p>
        </div>

        {/* Machine Indicator & Quick Action */}
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 px-3.5 py-2 bg-white rounded-lg border border-[#c5c6cd]/30 text-xs text-[#45474d] shadow-sm">
            <span className="material-symbols-outlined text-[#00743a] text-base">precision_manufacturing</span>
            <span className="font-bold text-[#051125]">PMA Granulator #01</span>
            <span className="text-[#c5c6cd]">•</span>
            <span>Granulation Line</span>
          </div>

          <button
            onClick={() => setIsDispatchModalOpen(true)}
            className="px-4 py-2 bg-[#229ED9] hover:bg-[#1e8bc0] text-white text-xs font-bold uppercase tracking-widest rounded-lg inline-flex items-center gap-2 transition-all shadow-sm active:scale-95 cursor-pointer"
            title="Dispatch daily summary to Telegram bot"
          >
            <svg className="w-4 h-4 fill-current shrink-0" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.46-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.429-.009-1.253-.242-1.865-.441-.751-.244-1.349-.374-1.297-.789.027-.216.324-.437.891-.663 3.498-1.524 5.831-2.529 7.001-3.014 3.331-1.386 4.025-1.627 4.477-1.635.099-.002.321.023.465.14.121.099.155.232.164.331-.01.066.01.285-.005.452z"/>
            </svg>
            <span>Send Telegram</span>
          </button>
        </div>
      </section>

      {/* Main Split Layout: 30-Day History (Left) + Full PDF Viewer (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* ========================================================= */}
        {/* LEFT COLUMN: 30-Day History Timeline (lg:col-span-4)     */}
        {/* ========================================================= */}
        <div className="lg:col-span-4 bg-white border border-[#c5c6cd]/30 rounded-xl p-5 shadow-sm flex flex-col h-[520px] lg:h-[calc(100vh-210px)] lg:min-h-[640px]">
          {/* Header & Date Controls */}
          <div className="space-y-3 pb-4 border-b border-[#c5c6cd]/20 shrink-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[#1b263b] text-base">calendar_month</span>
                <h3 className="font-bold text-xs uppercase tracking-widest text-[#051125]">Operational History</h3>
              </div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#75777d] bg-[#f1f4f3] px-2 py-0.5 rounded">
                Last 30 Days
              </span>
            </div>

            {/* Date Picker Input */}
            <div>
              <label className="form-label text-[10px] mb-1.5">
                Select Specific Date
              </label>
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => {
                  if (e.target.value) {
                    setSelectedDate(e.target.value);
                  }
                }}
                className="input-field py-2 text-xs font-semibold"
              />
            </div>

            {/* Filter Pills */}
            <div className="flex items-center gap-1 p-1 bg-[#f1f4f3] rounded-lg text-xs font-semibold">
              <button
                onClick={() => setHistoryFilter('all')}
                className={`flex-1 py-1.5 px-2 rounded-md transition-all text-center text-xs cursor-pointer ${
                  historyFilter === 'all'
                    ? 'bg-white text-[#051125] font-bold shadow-sm'
                    : 'text-[#75777d] hover:text-[#051125]'
                }`}
              >
                All Days
              </button>
              <button
                onClick={() => setHistoryFilter('issues')}
                className={`flex-1 py-1.5 px-2 rounded-md transition-all text-center flex items-center justify-center gap-1.5 text-xs cursor-pointer ${
                  historyFilter === 'issues'
                    ? 'bg-white text-[#805600] font-bold shadow-sm'
                    : 'text-[#75777d] hover:text-[#051125]'
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#805600]" />
                Issues Only
              </button>
            </div>
          </div>

          {/* Scrollable History List */}
          <div className="flex-1 overflow-y-auto space-y-2.5 pt-3 pr-1">
            {isLoadingHistory ? (
              <div className="py-16 text-center text-xs text-[#75777d]">
                <span className="material-symbols-outlined animate-spin text-2xl mb-2 text-[#1b263b]">progress_activity</span>
                <p>Loading history records...</p>
              </div>
            ) : filteredHistory.length === 0 ? (
              <div className="py-16 text-center text-xs text-[#75777d]">
                <span className="material-symbols-outlined text-3xl mb-2 opacity-40">event_busy</span>
                <p>No operational logs match this filter.</p>
              </div>
            ) : (
              filteredHistory.map((item) => {
                const isSelected = item.date === selectedDate;
                const isToday = item.date === getTodayWIB();
                const itemCfg = statusStyles[item.status] || statusStyles.normal;

                return (
                  <button
                    key={item.date}
                    onClick={() => setSelectedDate(item.date)}
                    className={`w-full text-left p-3.5 rounded-lg border transition-all flex flex-col gap-2 cursor-pointer ${
                      isSelected
                        ? `bg-[#f1f4f3] border-l-4 ${itemCfg.accent} border-t-[#c5c6cd]/30 border-r-[#c5c6cd]/30 border-b-[#c5c6cd]/30 shadow-sm ring-1 ring-[#051125]/10`
                        : 'bg-white hover:bg-[#f7faf9] border-[#c5c6cd]/30'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-xs text-[#051125]">
                          {formatDisplayDate(item.date)}
                        </span>
                        {isToday && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-black bg-[#1b263b] text-white uppercase tracking-wider">
                            TODAY
                          </span>
                        )}
                      </div>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-wider ${itemCfg.badge}`}>
                        {item.status_label || itemCfg.label}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-[#75777d]">
                      <span className="flex items-center gap-1">
                        <span className="material-symbols-outlined text-[13px]">inventory_2</span>
                        {item.batches_processed?.length > 0
                          ? `${item.batches_processed.length} Batch${item.batches_processed.length > 1 ? 'es' : ''}`
                          : 'No batches'}
                      </span>
                      {item.anomaly_count > 0 ? (
                        <span className={`font-bold ${item.critical_count > 0 ? 'text-[#ba1a1a]' : 'text-[#805600]'}`}>
                          {item.anomaly_count} Anomal{item.anomaly_count > 1 ? 'ies' : 'y'}
                        </span>
                      ) : (
                        <span className="text-[#00743a] font-semibold">100% Healthy</span>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* ========================================================= */}
        {/* RIGHT COLUMN: Official PDF Report Viewer (lg:col-span-8)  */}
        {/* ========================================================= */}
        <div className="lg:col-span-8 bg-white border border-[#c5c6cd]/30 rounded-xl p-6 shadow-sm flex flex-col h-[650px] lg:h-[calc(100vh-210px)] lg:min-h-[640px]">
          {/* Document Top Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#c5c6cd]/30 shrink-0">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-black tracking-widest uppercase text-[#75777d]">
                  Selected Report
                </span>
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-wider ${statusCfg.badge}`}>
                  {summaryData?.status_label || statusCfg.label}
                </span>
              </div>
              <h2 className="heading-secondary text-xl mt-0.5">
                {formatDisplayDate(selectedDate)}
              </h2>
              <div className="flex items-center gap-3 text-xs text-[#75777d] mt-1 flex-wrap">
                <span>Total Inferences: <strong className="text-[#051125]">{summaryData?.total_events || 0}</strong></span>
                <span className="text-[#c5c6cd]">•</span>
                <span>Batches: <strong className="text-[#051125]">{summaryData?.batches_processed?.length ? summaryData.batches_processed.join(', ') : 'None'}</strong></span>
                <span className="text-[#c5c6cd]">•</span>
                <span>Timezone: <strong className="text-[#051125]">WIB (UTC+7)</strong></span>
              </div>
            </div>

            {/* Actions: Download / Print / Open */}
            <div className="flex items-center gap-2 flex-wrap">
              {pdfBlobUrl && (
                <a
                  href={pdfBlobUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-secondary py-2 px-3 text-xs justify-center"
                  title="Open PDF report in new browser tab"
                >
                  <span className="material-symbols-outlined text-sm">open_in_new</span>
                  <span>New Tab</span>
                </a>
              )}

              <button
                onClick={handleDownloadPdf}
                disabled={isLoadingPdf}
                className="btn-secondary py-2 px-3 text-xs justify-center disabled:opacity-50 cursor-pointer"
                title="Download official PDF report file"
              >
                <span className="material-symbols-outlined text-base">download</span>
                <span>Download</span>
              </button>

              <button
                onClick={handlePrintPdf}
                disabled={isLoadingPdf}
                className="px-4 py-2 bg-[#1b263b] hover:bg-[#051125] text-white text-xs font-bold uppercase tracking-widest rounded-md inline-flex items-center gap-1.5 transition-all shadow-sm active:scale-95 disabled:opacity-50 cursor-pointer"
                title="Print PDF report"
              >
                <span className="material-symbols-outlined text-base">print</span>
                <span>Print PDF</span>
              </button>
            </div>
          </div>

          {/* PDF Viewer Container */}
          <div className="flex-1 w-full bg-[#f1f4f3] rounded-lg overflow-hidden border border-[#c5c6cd]/30 mt-4 relative flex items-center justify-center min-h-[400px]">
            {(isLoadingPdf || isLoadingSummary) ? (
              <div className="text-center text-xs text-[#75777d] p-8">
                <span className="material-symbols-outlined animate-spin text-3xl mb-2 text-[#00743a]">progress_activity</span>
                <p className="font-semibold text-[#051125]">Generating Official A4 PDF Report...</p>
                <p className="text-[11px] text-[#75777d] mt-1">Formatting Indonesian maintenance diagnosis & compliance checklists</p>
              </div>
            ) : summaryError ? (
              <div className="text-center text-xs text-[#ba1a1a] p-8 max-w-md">
                <span className="material-symbols-outlined text-3xl mb-2">error</span>
                <p className="font-bold">{summaryError}</p>
              </div>
            ) : pdfBlobUrl ? (
              <iframe
                src={pdfBlobUrl}
                title="Official SPMS Daily PDF Report"
                className="w-full h-full border-0 bg-white"
              />
            ) : (
              <div className="text-center text-xs text-[#75777d] p-8">
                <span className="material-symbols-outlined text-3xl mb-2 opacity-40">description</span>
                <p className="font-semibold">No report available for this date.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Dispatch Modal */}
      {isDispatchModalOpen && (
        <div className="fixed inset-0 bg-[#051125]/60 backdrop-blur-xs z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-[#c5c6cd]/30 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#c5c6cd]/30 pb-3">
              <div className="flex items-center gap-2">
                <svg className="w-6 h-6 text-[#229ED9] fill-current" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.46-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.429-.009-1.253-.242-1.865-.441-.751-.244-1.349-.374-1.297-.789.027-.216.324-.437.891-.663 3.498-1.524 5.831-2.529 7.001-3.014 3.331-1.386 4.025-1.627 4.477-1.635.099-.002.321.023.465.14.121.099.155.232.164.331-.01.066.01.285-.005.452z"/>
                </svg>
                <h3 className="font-black text-base text-[#051125]">
                  Send Summary to Telegram
                </h3>
              </div>
              <button
                onClick={() => setIsDispatchModalOpen(false)}
                className="text-[#75777d] hover:text-[#051125] text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-[#45474d] leading-relaxed">
              This will dispatch the Indonesian maintenance diagnosis for{' '}
              <strong className="text-[#051125]">{formatDisplayDate(selectedDate)}</strong> to all
              registered engineers via the official SPMS Telegram Bot.
            </p>

            {dispatchResult && (
              <div
                className={`p-3 rounded-lg text-xs font-bold ${
                  dispatchResult.success
                    ? 'bg-[#e8f5e9] text-[#006d37] border border-[#006d37]/20'
                    : 'bg-[#ffdad6] text-[#ba1a1a] border border-[#ba1a1a]/20'
                }`}
              >
                {dispatchResult.message}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setIsDispatchModalOpen(false)}
                className="btn-secondary py-2.5 px-4 text-xs cursor-pointer"
                disabled={isDispatching}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSendTelegram}
                disabled={isDispatching}
                className="px-4 py-2.5 bg-[#229ED9] hover:bg-[#1e8bc0] text-white text-xs font-bold uppercase tracking-widest rounded-md inline-flex items-center gap-2 transition-all shadow-sm active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {isDispatching ? (
                  <>
                    <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                    <span>Sending...</span>
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4 fill-current shrink-0" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.46-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.429-.009-1.253-.242-1.865-.441-.751-.244-1.349-.374-1.297-.789.027-.216.324-.437.891-.663 3.498-1.524 5.831-2.529 7.001-3.014 3.331-1.386 4.025-1.627 4.477-1.635.099-.002.321.023.465.14.121.099.155.232.164.331-.01.066.01.285-.005.452z"/>
                    </svg>
                    <span>Send Now</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
