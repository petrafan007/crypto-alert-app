// Mirrors services/webull_service.validate_webull_combo_orders so the ticket
// can show Webull's known rejections before a 2FA code is used. The server
// still validates every order; this only gives earlier, clearer feedback.

export const WEBULL_COMBO_MIN_PRICE_GAP_RATIO = 0.001;

const price = (value) => {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.round(number * 10000) / 10000 : null;
};

const easternParts = (now) => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(now).map((p) => [p.type, p.value]));
  return { weekday: parts.weekday, minutes: Number(parts.hour) % 24 * 60 + Number(parts.minute) };
};

// Weekday 9:30-16:00 ET. Exchange holidays are checked by the server.
export const isRegularSessionNow = (now = new Date()) => {
  const { weekday, minutes } = easternParts(now);
  return !['Sat', 'Sun'].includes(weekday) && minutes >= 570 && minutes < 960;
};

export function validateWebullComboLegs(legs, { symbol = '', checkMarketHours = false, now = new Date() } = {}) {
  const errors = [];
  const linked = [];
  (legs || []).forEach((leg, i) => {
    const index = i + 1;
    const side = String(leg.side || '').toUpperCase();
    let orderType = String(leg.order_type || leg.type || '').toUpperCase();
    orderType = { STOP_LIMIT: 'STOP_LOSS_LIMIT', STOP: 'STOP_LOSS' }[orderType] || orderType;
    const limit = price(leg.limit_price ?? leg.price);
    const stop = price(leg.stop_price ?? leg.stopPrice);
    if (orderType === 'STOP_LOSS_LIMIT' && limit !== null && stop !== null) {
      if (side === 'BUY' && limit < stop) {
        errors.push(`Leg #${index}: a Buy Stop Limit triggers when price rises to the stop (${stop}), so its limit (${limit}) must be at or above the stop. Check that the prices are not swapped.`);
      }
      if (['SELL', 'SHORT'].includes(side) && limit > stop) {
        errors.push(`Leg #${index}: a Sell Stop Limit triggers when price falls to the stop (${stop}), so its limit (${limit}) must be at or below the stop. Check that the prices are not swapped.`);
      }
    }
    const role = String(leg.combo_type || leg.role || '').toUpperCase();
    if (['OCO', 'OTOCO'].includes(role)) {
      linked.push({ index, symbol: String(leg.symbol || symbol || '').toUpperCase(), side, price: limit ?? stop });
    }
  });
  linked.forEach((leg, position) => {
    linked.slice(0, position).forEach((other) => {
      if (leg.symbol !== other.symbol || leg.side !== other.side) return;
      if (leg.price === other.price) {
        errors.push(`Legs #${other.index} and #${leg.index} are identical. Webull requires linked OCO legs to differ in price or side.`);
      } else if (leg.price !== null && other.price !== null
        && Math.abs(leg.price - other.price) < Math.max(leg.price, other.price) * WEBULL_COMBO_MIN_PRICE_GAP_RATIO) {
        errors.push(`Legs #${other.index} and #${leg.index} are priced too close together (${other.price} and ${leg.price}). Webull rejects nearly equal linked OCO prices; widen the gap.`);
      }
    });
  });
  if (checkMarketHours && (legs || []).some((leg) => String(leg.support_trading_session || leg.session || 'CORE').toUpperCase() === 'CORE')
    && !isRegularSessionNow(now)) {
    errors.push('Webull accepts conditional (OTO / OCO / OTOCO) orders only during regular market hours, 9:30 AM - 4:00 PM ET on trading days.');
  }
  return errors;
}
