export const CHART_RANGES = [
  { value: '1d', label: '1 Day (1D)', interval: '5m', limit: 288, intervalSeconds: 300 },
  { value: '3d', label: '3 Days (3D)', interval: '15m', limit: 288, intervalSeconds: 900 },
  { value: '5d', label: '5 Days (5D)', interval: '30m', limit: 240, intervalSeconds: 1800 },
  { value: '7d', label: '1 Week (1W)', interval: '1h', limit: 168, intervalSeconds: 3600 },
  { value: '14d', label: '2 Weeks (2W)', interval: '1h', limit: 336, intervalSeconds: 3600 },
  { value: '30d', label: '1 Month (1M)', interval: '1h', limit: 720, intervalSeconds: 3600 },
  { value: '90d', label: '3 Months (3M)', interval: '4h', limit: 540, intervalSeconds: 14400 },
  { value: '180d', label: '6 Months (6M)', interval: '6h', limit: 720, intervalSeconds: 21600 },
  { value: '365d', label: '1 Year (1Y)', interval: '12h', limit: 730, intervalSeconds: 43200 },
  { value: '730d', label: '2 Years (2Y)', interval: '1d', limit: 730, intervalSeconds: 86400 },
  { value: 'all', label: 'All Available (ALL)', interval: '1w', limit: 1000, intervalSeconds: 604800 },
];

export const DEFAULT_CHART_RANGE = '30d';

export const getChartRange = value => CHART_RANGES.find(range => range.value === value)
  || CHART_RANGES.find(range => range.value === DEFAULT_CHART_RANGE);

export const formatChartTick = (time, rangeValue) => {
  const date = new Date(Number(time) * 1000);
  const options = rangeValue === '1d'
    ? { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }
    : rangeValue === '3d'
      ? { weekday: 'short', hour: 'numeric', timeZone: 'UTC' }
      : ['5d', '7d', '14d', '30d', '90d', '180d'].includes(rangeValue)
        ? { month: 'short', day: 'numeric', timeZone: 'UTC' }
        : { month: 'short', year: 'numeric', timeZone: 'UTC' };
  return new Intl.DateTimeFormat('en-US', options).format(date);
};
