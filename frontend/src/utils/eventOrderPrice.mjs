export const formatEventLimitPrice = (value) => {
  if (value == null || String(value).trim() === '') return '';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '';
  const cents = parsed.toFixed(2);
  // Pad USD cents while retaining valid fractional-cent contract ticks.
  return Number(cents) === parsed ? cents : String(parsed);
};
