import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';
import { GLOBAL_MODE_STORAGE_KEY, normalizeGlobalMode } from '../utils/globalMode.mjs';

const GlobalModeContext = createContext({
  globalMode: 'real',
  setGlobalMode: async () => {},
  isRealMode: true,
  isPaperMode: false,
  isQseMode: false,
  isAdmin: false,
  modeLoading: false,
});

export function useGlobalMode() {
  return useContext(GlobalModeContext);
}

function applyModeToDocument(mode) {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-trading-mode', mode);
  document.body.classList.remove('mode-real', 'mode-paper', 'mode-qse');
  document.body.classList.add(`mode-${mode}`);
}

export function GlobalModeProvider({ children }) {
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin || user?.id === 1);

  const [globalMode, setGlobalModeState] = useState(() => {
    try {
      const stored = localStorage.getItem(GLOBAL_MODE_STORAGE_KEY);
      // Allow stored qse before user finishes hydrating; coerce once user is known.
      return ['real', 'paper', 'qse'].includes(stored) ? stored : 'real';
    } catch {
      return 'real';
    }
  });
  const [modeLoading, setModeLoading] = useState(false);

  // Immediately apply mode attributes/classes to document root & body
  useEffect(() => {
    const effective = user ? normalizeGlobalMode(globalMode, isAdmin) : (globalMode === 'qse' ? 'real' : globalMode);
    applyModeToDocument(effective);
  }, [globalMode, user, isAdmin]);

  // Coerce stored 'qse' back to 'real' if a non-admin logs in
  useEffect(() => {
    if (user && !isAdmin && globalMode === 'qse') {
      setGlobalModeState('real');
      try {
        localStorage.setItem(GLOBAL_MODE_STORAGE_KEY, 'real');
      } catch {}
    }
  }, [user, isAdmin, globalMode]);

  // Hydrate persisted global mode from backend session/endpoint once logged in
  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    if (user.global_trading_mode) {
      const fromSession = normalizeGlobalMode(user.global_trading_mode, isAdmin);
      setGlobalModeState(fromSession);
      try {
        localStorage.setItem(GLOBAL_MODE_STORAGE_KEY, fromSession);
      } catch {}
    }
    axios.get('/api/global-mode', { withCredentials: true, timeout: 15000 })
      .then((res) => {
        if (cancelled) return;
        const serverMode = normalizeGlobalMode(res.data?.mode, Boolean(res.data?.is_admin ?? isAdmin));
        setGlobalModeState(serverMode);
        try {
          localStorage.setItem(GLOBAL_MODE_STORAGE_KEY, serverMode);
        } catch {}
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.global_trading_mode, isAdmin]);

  const setGlobalMode = useCallback(async (nextMode) => {
    const normalized = normalizeGlobalMode(nextMode, isAdmin);
    if (nextMode === 'qse' && !isAdmin) return false;
    setModeLoading(true);
    try {
      const res = await axios.post('/api/global-mode', { mode: normalized }, { withCredentials: true });
      const confirmed = normalizeGlobalMode(res.data?.mode || normalized, isAdmin);
      setGlobalModeState(confirmed);
      try {
        localStorage.setItem(GLOBAL_MODE_STORAGE_KEY, confirmed);
        // Update cached session object so reload matches immediately
        const cached = sessionStorage.getItem('cda_user_session');
        if (cached) {
          const parsed = JSON.parse(cached);
          parsed.global_trading_mode = confirmed;
          sessionStorage.setItem('cda_user_session', JSON.stringify(parsed));
        }
      } catch {}
      applyModeToDocument(confirmed);
      window.dispatchEvent(new CustomEvent('app:global-mode-changed', { detail: { mode: confirmed } }));
      return true;
    } catch (err) {
      console.error('Failed to switch global mode:', err);
      return false;
    } finally {
      setModeLoading(false);
    }
  }, [isAdmin]);

  const effectiveMode = user ? normalizeGlobalMode(globalMode, isAdmin) : 'real';

  const value = useMemo(() => ({
    globalMode: effectiveMode,
    setGlobalMode,
    isRealMode: effectiveMode === 'real',
    isPaperMode: effectiveMode === 'paper',
    isQseMode: effectiveMode === 'qse',
    isAdmin,
    modeLoading,
  }), [effectiveMode, setGlobalMode, isAdmin, modeLoading]);

  return (
    <GlobalModeContext.Provider value={value}>
      {children}
    </GlobalModeContext.Provider>
  );
}
