/**
 * Clean broker/API error text before rendering in user-facing modals or toasts.
 * Strips internal OPENAPI_* codes, HTTP status prefixes, Binance APIError(code=...)
 * wrappers, and provider Request IDs while preserving the actual plain-English message.
 */
export function cleanUserErrorMessage(raw) {
  if (raw == null) return '';
  let text = String(raw).trim();
  if (!text) return '';

  // Clarify Webull's misleading overnight hours error if it ever arrives raw
  if (/OPENAPI_OVERNIGHT_CAN_NOT_TRADING_FOR_NON_TRADING_HOURS/i.test(text)
      || (/overnight trading is only available/i.test(text) && !/sunday through thursday/i.test(text))) {
    return "Overnight Trading is currently closed. Webull's Overnight Session operates Sunday through Thursday from 8:00 PM to 4:00 AM ET (closed Friday night and Saturday). Switch Trading Session to Including Extended Hours or Only Regular Hours to queue your order for the next trading day.";
  }

  // Strip wrapper prefixes
  text = text.replace(/^Webull\s+[\w\s-]+?\s+failed\s*\(HTTP\s*\d+\):\s*/i, '');
  text = text.replace(/^APIError\(code=-?\d+\):\s*/i, '');
  text = text.replace(/^BinanceAPIException:\s*/i, '');
  text = text.replace(/^HTTP\s*\d{3}:\s*/i, '');

  // Strip provider request IDs and internal API error codes
  text = text.replace(/\s*\(Webull\s+request\s+ID:[^)]*\)/gi, '');
  text = text.replace(/\s*\(Request\s+ID:[^)]*\)/gi, '');
  text = text.replace(/\s*\(OPENAPI_[A-Z0-9_]+\)/g, '');
  text = text.replace(/\bOPENAPI_[A-Z0-9_]+\b/g, '');
  text = text.replace(/\s*\(HTTP\s*\d{3}\)/gi, '');
  text = text.replace(/\s*\(code\s*=\s*-?\d+\)/gi, '');
  text = text.replace(/\s*\[\s*code\s*[:=]\s*-?\d+\s*\]/gi, '');

  // Tidy whitespace and stray punctuation
  text = text.replace(/\s{2,}/g, ' ').replace(/\s+([.,;:!?])/g, '$1').trim();
  return text;
}

/**
 * Return true only during Webull's actual US Overnight Trading window:
 * Sunday 8:00 PM ET through Friday 4:00 AM ET (Sun–Thu 20:00–24:00, Mon–Fri 00:00–04:00).
 * Closed Friday 8:00 PM ET through Sunday 8:00 PM ET.
 */
export function isWebullOvernightWindow(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(now);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  const dayMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const day = dayMap[map.weekday];
  const hour = Number(map.hour) % 24;
  const minute = Number(map.minute);
  const minutes = hour * 60 + minute;

  // Sunday–Thursday 8:00 PM to midnight ET
  if (day >= 0 && day <= 4 && minutes >= 20 * 60) return true;
  // Monday–Friday midnight to 4:00 AM ET
  if (day >= 1 && day <= 5 && minutes < 4 * 60) return true;
  return false;
}

/**
 * Determine the smart default Webull equity trading session for US Eastern time.
 * Never defaults to NIGHT during the Friday 8:00 PM – Sunday 8:00 PM ET weekend closure.
 */
export function defaultWebullTradingSession(now = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(now);
    const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    const dayMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const day = dayMap[map.weekday];
    const hour = Number(map.hour) % 24;
    const minute = Number(map.minute);
    const minutes = hour * 60 + minute;

    const isWeekday = day >= 1 && day <= 5;
    if (isWeekday && minutes >= 9 * 60 + 30 && minutes < 16 * 60) return 'CORE';
    if (isWeekday && ((minutes >= 4 * 60 && minutes < 9 * 60 + 30) || (minutes >= 16 * 60 && minutes < 20 * 60))) return 'ALL';
    if (isWebullOvernightWindow(now)) return 'NIGHT';
    // Weekend closure (Fri 8:00 PM – Sun 8:00 PM ET): default to Extended Hours for next session
    return 'ALL';
  } catch {
    return 'CORE';
  }
}
