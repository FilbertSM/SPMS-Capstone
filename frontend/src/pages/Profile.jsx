import React, { useEffect, useState } from 'react';
import { fetchJsonWithAuth } from '../utils/api';

const TELEGRAM_LINK_POLL_INTERVAL_MS = 3000;
const TELEGRAM_LINK_POLL_TIMEOUT_MS = 120000;

const Profile = () => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [preferenceStatus, setPreferenceStatus] = useState(null);
  const [isSavingPreference, setIsSavingPreference] = useState(false);

  const [telegramStatus, setTelegramStatus] = useState(null);
  const [telegramLink, setTelegramLink] = useState(null);
  const [isLinkingTelegram, setIsLinkingTelegram] = useState(false);
  const [isSavingTelegram, setIsSavingTelegram] = useState(false);
  const [telegramStatusMessage, setTelegramStatusMessage] = useState(null);

  useEffect(() => {
    let ignore = false;

    const fetchProfile = async () => {
      try {
        setIsLoading(true);
        const data = await fetchJsonWithAuth('/api/users/me');
        if (!ignore) {
          setUser(data);
          setError(null);
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    };

    const fetchTelegramStatus = async () => {
      try {
        const data = await fetchJsonWithAuth('/api/users/me/telegram/status');
        if (!ignore) {
          setTelegramStatus(data);
        }
      } catch (err) {
        if (!ignore) {
          setTelegramStatusMessage({ type: 'error', message: err.message });
        }
      }
    };

    fetchProfile();
    fetchTelegramStatus();
    return () => {
      ignore = true;
    };
  }, []);

  const handleLinkTelegram = async () => {
    setIsLinkingTelegram(true);
    setTelegramStatusMessage(null);
    try {
      const payload = await fetchJsonWithAuth('/api/users/me/telegram/link-token', { method: 'POST' });
      setTelegramLink(payload);
      window.open(payload.deep_link, '_blank', 'noopener,noreferrer');

      const startedAt = Date.now();
      const poll = setInterval(async () => {
        if (Date.now() - startedAt > TELEGRAM_LINK_POLL_TIMEOUT_MS) {
          clearInterval(poll);
          setIsLinkingTelegram(false);
          setTelegramStatusMessage({ type: 'error', message: 'Linking timed out. Try again if you did not complete the Telegram step.' });
          return;
        }
        try {
          const status = await fetchJsonWithAuth('/api/users/me/telegram/status');
          if (status.linked) {
            clearInterval(poll);
            setTelegramStatus(status);
            setTelegramLink(null);
            setIsLinkingTelegram(false);
            setTelegramStatusMessage({ type: 'success', message: 'Telegram linked successfully.' });
          }
        } catch (err) {
          clearInterval(poll);
          setIsLinkingTelegram(false);
          setTelegramStatusMessage({ type: 'error', message: err.message });
        }
      }, TELEGRAM_LINK_POLL_INTERVAL_MS);
    } catch (err) {
      setIsLinkingTelegram(false);
      setTelegramStatusMessage({ type: 'error', message: err.message });
    }
  };

  const handleToggleTelegramNotifications = async () => {
    if (!telegramStatus?.linked) return;
    const nextValue = !telegramStatus.notifications_enabled;
    setIsSavingTelegram(true);
    setTelegramStatusMessage(null);
    try {
      const status = await fetchJsonWithAuth('/api/users/me/telegram/notifications', {
        method: 'PATCH',
        body: JSON.stringify({ enabled: nextValue }),
      });
      setTelegramStatus(status);
      setTelegramStatusMessage({ type: 'success', message: 'Telegram notification preference saved.' });
    } catch (err) {
      setTelegramStatusMessage({ type: 'error', message: err.message });
    } finally {
      setIsSavingTelegram(false);
    }
  };

  const handleUnlinkTelegram = async () => {
    setIsSavingTelegram(true);
    setTelegramStatusMessage(null);
    try {
      const status = await fetchJsonWithAuth('/api/users/me/telegram/link', { method: 'DELETE' });
      setTelegramStatus(status);
      setTelegramStatusMessage({ type: 'success', message: 'Telegram account unlinked.' });
    } catch (err) {
      setTelegramStatusMessage({ type: 'error', message: err.message });
    } finally {
      setIsSavingTelegram(false);
    }
  };

  const handleToggleNotifications = async () => {
    if (!user) return;

    const nextValue = !user.email_notifications;
    setIsSavingPreference(true);
    setPreferenceStatus(null);

    try {
      const payload = await fetchJsonWithAuth('/api/users/me/preferences', {
        method: 'PATCH',
        body: JSON.stringify({ email_notifications: nextValue }),
      });
      setUser((current) => ({
        ...current,
        email_notifications: Boolean(payload.email_notifications),
      }));
      setPreferenceStatus({ type: 'success', message: 'Preference saved to backend.' });
    } catch (err) {
      setPreferenceStatus({ type: 'error', message: err.message });
    } finally {
      setIsSavingPreference(false);
    }
  };

  if (isLoading) {
    return (
      <div className="page-container flex items-center justify-center">
        <span className="material-symbols-outlined animate-spin text-4xl text-[#1b263b]">sync</span>
      </div>
    );
  }

  return (
    <div className="page-container">
      <div className="max-w-4xl mx-auto space-y-8">
        <div>
          <h2 className="text-2xl font-bold text-[#051125] font-headline">My Profile</h2>
          <p className="text-sm text-[#45474d]">
            Backend account fields currently exposed by the SPMS API.
          </p>
        </div>

        {error && (
          <div className="bg-[#ffdad6] border border-[#ba1a1a]/20 text-[#ba1a1a] rounded-lg px-4 py-3 text-sm font-bold">
            Profile unavailable: {error}
          </div>
        )}

        <div className="bg-[#051125] rounded-xl border border-[#c5c6cd]/20 shadow-md overflow-hidden text-white">
          <div className="h-24 bg-[#1b263b] relative"></div>

          <div className="px-8 pb-8 relative">
            <div className="absolute -top-12 flex items-end gap-4">
              <div className="w-24 h-24 rounded-full bg-[#f1f4f3] border-4 border-[#051125] flex items-center justify-center shadow-md">
                <span className="material-symbols-outlined text-5xl text-[#45474d]">person</span>
              </div>
            </div>

            <div className="pt-16 flex justify-between items-start">
              <div>
                <h3 className="text-2xl font-bold text-white">{user?.full_name || 'Unknown user'}</h3>
                <p className="text-[#c5c6cd]">{user?.email || 'No email returned'}</p>
                <div className="flex flex-wrap gap-2 mt-3">
                  <span className="inline-block px-3 py-1 bg-[#2ecc71]/10 text-[#2ecc71] text-xs font-bold uppercase tracking-widest rounded-full border border-[#2ecc71]/20">
                    {user?.role || 'role unavailable'}
                  </span>
                  <span className={`inline-block px-3 py-1 text-xs font-bold uppercase tracking-widest rounded-full border ${
                    user?.is_active ? 'bg-[#2ecc71]/10 text-[#2ecc71] border-[#2ecc71]/20' : 'bg-[#ffdad6]/10 text-[#ffdad6] border-[#ffdad6]/20'
                  }`}>
                    {user?.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>
            </div>

            <div className="h-px bg-[#c5c6cd]/10 my-8"></div>

            <h4 className="text-sm font-bold text-white uppercase tracking-widest mb-4">Security & Access</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
              <div className="p-4 bg-[#1b263b]/40 rounded-xl border border-[#c5c6cd]/10">
                <p className="text-xs text-[#c5c6cd] uppercase tracking-widest mb-1">Account Email</p>
                <p className="text-sm font-bold text-white">{user?.email || '-'}</p>
              </div>
              <div className="p-4 bg-[#1b263b]/40 rounded-xl border border-[#c5c6cd]/10">
                <p className="text-xs text-[#c5c6cd] uppercase tracking-widest mb-1">Access Role</p>
                <p className="text-sm font-bold text-white">{user?.role || '-'}</p>
              </div>
            </div>

            <h4 className="text-sm font-bold text-white uppercase tracking-widest mb-4">Preferences</h4>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-[#1b263b]/40 rounded-xl border border-[#c5c6cd]/10">
              <div>
                <p className="text-sm font-bold text-white">Email Notifications</p>
                <p className="text-xs text-[#c5c6cd] mt-1">
                  Stored by the backend as <span className="font-bold">email_notifications</span> on your account.
                </p>
                {preferenceStatus && (
                  <p className={`text-xs font-bold mt-2 ${preferenceStatus.type === 'success' ? 'text-[#6bfe9c]' : 'text-[#ffdad6]'}`}>
                    {preferenceStatus.message}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={handleToggleNotifications}
                disabled={isSavingPreference}
                className={`w-12 h-6 rounded-full relative flex items-center transition-colors disabled:opacity-60 ${
                  user?.email_notifications ? 'bg-[#2ecc71]' : 'bg-[#45474d]'
                }`}
                title="Toggle email notifications"
              >
                <div className={`w-4 h-4 bg-white rounded-full absolute transition-transform ${
                  user?.email_notifications ? 'translate-x-7' : 'translate-x-1'
                }`}></div>
              </button>
            </div>

            <div className="flex flex-col gap-4 p-4 mt-4 bg-[#1b263b]/40 rounded-xl border border-[#c5c6cd]/10">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-bold text-white">Telegram Notifications</p>
                  <p className="text-xs text-[#c5c6cd] mt-1">
                    {telegramStatus?.linked
                      ? 'Your account is linked to the SPMS Telegram bot.'
                      : 'Link your Telegram account to receive alert notifications, if an admin has granted you access.'}
                  </p>
                  {telegramStatusMessage && (
                    <p className={`text-xs font-bold mt-2 ${telegramStatusMessage.type === 'success' ? 'text-[#6bfe9c]' : 'text-[#ffdad6]'}`}>
                      {telegramStatusMessage.message}
                    </p>
                  )}
                  {telegramLink && (
                    <p className="text-xs text-[#c5c6cd] mt-2">
                      Waiting for confirmation in Telegram… Didn&apos;t open?{' '}
                      <a href={telegramLink.deep_link} target="_blank" rel="noopener noreferrer" className="underline text-white">
                        Open the link again
                      </a>.
                    </p>
                  )}
                </div>

                {telegramStatus?.linked ? (
                  <button
                    type="button"
                    onClick={handleToggleTelegramNotifications}
                    disabled={isSavingTelegram}
                    className={`w-12 h-6 rounded-full relative flex items-center transition-colors disabled:opacity-60 ${
                      telegramStatus?.notifications_enabled ? 'bg-[#2ecc71]' : 'bg-[#45474d]'
                    }`}
                    title="Toggle Telegram notifications"
                  >
                    <div className={`w-4 h-4 bg-white rounded-full absolute transition-transform ${
                      telegramStatus?.notifications_enabled ? 'translate-x-7' : 'translate-x-1'
                    }`}></div>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleLinkTelegram}
                    disabled={isLinkingTelegram}
                    className="btn-primary whitespace-nowrap disabled:opacity-60"
                  >
                    {isLinkingTelegram ? 'Waiting for Telegram…' : 'Link Telegram'}
                  </button>
                )}
              </div>

              {telegramStatus?.linked && (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={handleUnlinkTelegram}
                    disabled={isSavingTelegram}
                    className="text-xs font-bold text-[#ffdad6] underline disabled:opacity-60"
                  >
                    Unlink Telegram
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Profile;
