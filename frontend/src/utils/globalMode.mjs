export const VALID_GLOBAL_MODES = ['real', 'paper', 'qse'];
export const GLOBAL_MODE_STORAGE_KEY = 'global_trading_mode';

/**
 * Normalize a global trading mode value and enforce admin gating on QSE.
 */
export function normalizeGlobalMode(raw, isAdmin = false) {
  const value = String(raw || '').trim().toLowerCase();
  if (!VALID_GLOBAL_MODES.includes(value)) return 'real';
  if (value === 'qse' && !isAdmin) return 'real';
  return value;
}

/**
 * Map global mode to WebullTrading's internal mode identifier.
 */
export function toWebullTradingMode(globalMode) {
  if (globalMode === 'qse') return 'QUANT';
  if (globalMode === 'paper') return 'TEST';
  return 'REAL';
}

/**
 * Create a race-safe request coordinator guard keyed on (mode, fetchId).
 * Any response resolving after a mode switch or newer fetch is dropped.
 */
export function createModeRaceGuard(initialMode = 'real') {
  let currentMode = normalizeGlobalMode(initialMode, true);
  let seq = 0;
  return {
    getMode() {
      return currentMode;
    },
    setMode(nextMode) {
      const normalized = normalizeGlobalMode(nextMode, true);
      if (normalized !== currentMode) {
        currentMode = normalized;
        seq += 1;
      }
      return { mode: currentMode, ticket: seq };
    },
    issueTicket() {
      seq += 1;
      return { mode: currentMode, ticket: seq };
    },
    isCurrent(issued) {
      return Boolean(issued) && issued.mode === currentMode && issued.ticket === seq;
    },
  };
}

/**
 * Determine whether a row action is permitted in the active global mode.
 * QSE is strictly read-only everywhere.
 */
export function canPerformRowAction(globalMode, actionType) {
  if (globalMode === 'qse') return false;
  if (globalMode === 'paper') {
    const allowedPaper = new Set(['buy', 'sell', 'hide', 'watchlist_add', 'watchlist_remove', 'cancel_paper']);
    return allowedPaper.has(String(actionType || '').toLowerCase());
  }
  return true;
}

/**
 * Scope a table persistence key by active trading mode ('real' | 'paper' | 'qse').
 * Real mode retains the existing unsuffixed key so prior user customizations stay intact.
 */
export function scopedTableKey(baseKey, mode = 'real') {
  const normalized = String(mode || 'real').trim().toLowerCase();
  if (!normalized || normalized === 'real') return baseKey;
  return `${baseKey}:${normalized}`;
}
