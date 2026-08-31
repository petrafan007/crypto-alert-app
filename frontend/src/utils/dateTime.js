export const EASTERN_TIME_ZONE = 'America/New_York';

const UTC_OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const ISO_WITHOUT_ZONE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

export const parseAppTimestamp = (value) => {
  if (value instanceof Date) return new Date(value.getTime());
  if (value === undefined || value === null || value === '') return null;
  if (typeof value === 'number') {
    const milliseconds = Math.abs(value) < 1e12 ? value * 1000 : value;
    const parsedNumber = new Date(milliseconds);
    return Number.isNaN(parsedNumber.getTime()) ? null : parsedNumber;
  }
  const text = String(value).trim();
  // The backend stores database timestamps as naive UTC ISO strings. Browsers
  // otherwise interpret those strings as local time, producing a four-hour
  // shift for Eastern users during daylight saving time.
  const normalized = ISO_WITHOUT_ZONE.test(text) && !UTC_OFFSET_SUFFIX.test(text)
    ? `${text.replace(' ', 'T')}Z`
    : text;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const formatEastern = (value, options, fallback = '—') => {
  const parsed = parseAppTimestamp(value);
  if (!parsed) return value ? String(value) : fallback;
  return new Intl.DateTimeFormat('en-US', {
    timeZone: EASTERN_TIME_ZONE,
    ...options,
  }).format(parsed);
};

export const formatEasternDate = (value, options = {}) => formatEastern(value, {
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  ...options,
});

export const formatEasternTime = (value, options = {}) => formatEastern(value, {
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
  ...options,
});

export const formatEasternDateTime = (value, options = {}) => formatEastern(value, {
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
  ...options,
});

const easternDateParts = (value = new Date()) => {
  const parsed = parseAppTimestamp(value);
  if (!parsed) return null;
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: EASTERN_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(parsed);
  const read = (type) => Number(parts.find((part) => part.type === type)?.value);
  return { year: read('year'), month: read('month'), day: read('day') };
};

export const differenceInEasternCalendarDays = (dateOnly, now = new Date()) => {
  const match = String(dateOnly || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const today = easternDateParts(now);
  if (!match || !today) return 0;
  const expirationKey = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const todayKey = Date.UTC(today.year, today.month - 1, today.day);
  return Math.max(0, Math.round((expirationKey - todayKey) / 86400000));
};

