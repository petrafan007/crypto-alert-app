import React, { useEffect, useState } from 'react';
import './CryptoIcon.css';

const iconCache = new Map();
const iconRequests = new Map();
const queuedSymbols = new Set();
const queuedResolvers = new Map();
let batchTimer = null;

const normalizeAssetSymbol = (symbol) => {
  let clean = String(symbol || '').toUpperCase().trim();
  if (clean.includes('/')) clean = clean.split('/')[0];
  if (clean.endsWith('USDT') && clean.length > 4) clean = clean.slice(0, -4);
  else if (clean.endsWith('USD') && clean.length > 3) clean = clean.slice(0, -3);
  return clean.replace(/[^A-Z0-9]/g, '').slice(0, 20);
};

const flushIconBatch = async () => {
  const symbols = Array.from(queuedSymbols);
  symbols.forEach((symbol) => queuedSymbols.delete(symbol));
  batchTimer = null;

  let icons = {};
  try {
    const response = await fetch('/api/asset-icons', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols }),
    });
    if (response.ok) icons = (await response.json())?.icons || {};
  } catch {
    icons = {};
  }

  symbols.forEach((symbol) => {
    const payload = icons[symbol];
    const result = payload?.icon_url ? {
      url: payload.icon_url,
      name: payload.asset_name || symbol,
      provider: payload.provider || 'CoinGecko',
    } : null;
    if (result) iconCache.set(symbol, result);
    (queuedResolvers.get(symbol) || []).forEach((resolve) => resolve(result));
    queuedResolvers.delete(symbol);
    iconRequests.delete(symbol);
  });

  if (queuedSymbols.size && !batchTimer) batchTimer = setTimeout(flushIconBatch, 40);
};

const resolveIcon = (symbol) => {
  if (iconCache.has(symbol)) return Promise.resolve(iconCache.get(symbol));
  if (iconRequests.has(symbol)) return iconRequests.get(symbol);

  const request = new Promise((resolve) => {
    queuedSymbols.add(symbol);
    if (!queuedResolvers.has(symbol)) queuedResolvers.set(symbol, []);
    queuedResolvers.get(symbol).push(resolve);
    if (!batchTimer) batchTimer = setTimeout(flushIconBatch, 40);
  });

  iconRequests.set(symbol, request);
  return request;
};

export const CryptoIcon = ({ symbol, size = 20, className = '' }) => {
  const cleanSymbol = normalizeAssetSymbol(symbol);
  const [icon, setIcon] = useState(() => iconCache.get(cleanSymbol) || null);
  const [loaded, setLoaded] = useState(() => iconCache.has(cleanSymbol));

  useEffect(() => {
    let active = true;
    if (!cleanSymbol) {
      setIcon(null);
      setLoaded(true);
      return () => { active = false; };
    }

    setIcon(iconCache.get(cleanSymbol) || null);
    setLoaded(iconCache.has(cleanSymbol));
    resolveIcon(cleanSymbol).then((result) => {
      if (!active) return;
      setIcon(result);
      setLoaded(true);
    });
    return () => { active = false; };
  }, [cleanSymbol]);

  if (!cleanSymbol) return null;

  if (!loaded || !icon?.url) {
    return (
      <span
        className={`crypto-coin-icon-placeholder ${className}`}
        style={{ width: `${size}px`, height: `${size}px` }}
        aria-hidden="true"
      />
    );
  }

  return (
    <span
      className={`crypto-coin-icon-wrapper ${className}`}
      style={{ width: `${size}px`, height: `${size}px` }}
      title={`${icon.name} icon provided by ${icon.provider}`}
    >
      <img
        src={icon.url}
        alt={`${icon.name} icon`}
        width={size}
        height={size}
        className="crypto-coin-img"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => {
          iconCache.delete(cleanSymbol);
          setIcon(null);
        }}
      />
    </span>
  );
};

// Exchange brand marks are not asset-symbol icons. They remain local so the
// onboarding and account-source UI never depends on a third-party image host.
export const BinanceLogo = ({ size = 28, style = {} }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" style={{ verticalAlign: 'middle', display: 'inline-block', flexShrink: 0, ...style }}>
    <circle cx="16" cy="16" r="16" fill="#F3BA2F" />
    <path d="M16 6.5l3.5 3.5-3.5 3.5-3.5-3.5L16 6.5zm-5.5 5.5l3.5 3.5L10.5 19 7 15.5l3.5-3.5zm11 0l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zM16 15.5l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zm0 9l3.5-3.5 3.5 3.5L16 28l-7-3.5 3.5-3.5 3.5 3.5z" fill="#FFF" />
  </svg>
);

export const WebullLogo = ({ size = 28, style = {} }) => (
  <svg width={size} height={size} viewBox="0 0 52 52" fill="none" style={{ verticalAlign: 'middle', display: 'inline-block', flexShrink: 0, ...style }}>
    <rect width="52" height="52" rx="12" fill="#205BFF" />
    <path transform="translate(3.615, 13)" d="M41.7832962,0 C41.9459106,0 42.0882746,0.0866854658 42.1666825,0.216359069 C43.8289923,2.66540836 44.7676281,5.46271319 44.7676281,8.43208061 C44.7676281,18.1345746 34.7460532,26 22.383814,26 C10.0215749,26 0,18.1345746 0,8.43208061 C0,5.46716016 0.935826425,2.67378733 2.58829888,0.223985685 C2.67109477,0.0916264068 2.81687473,0 2.9840593,0 C3.23130408,0 3.43173558,0.200393004 3.43173558,0.447590303 C3.43173558,0.475056669 3.42926112,0.501945205 3.42452292,0.528045226 L3.41810883,0.550292077 C3.37800671,0.861741908 3.3575721,1.17661276 3.3575721,1.49443092 C3.3575721,7.98336 11.2132389,12.5742305 22.383814,12.5742305 C33.5543891,12.5742305 41.410056,7.98336 41.410056,1.49443092 C41.410056,1.17865223 41.3898828,0.865783153 41.3502888,0.556288325 C41.3402868,0.521941442 41.3356199,0.48531078 41.3356199,0.447590303 C41.3356199,0.200393004 41.5360514,0 41.7832962,0 Z" fill="#FFFFFF" />
  </svg>
);

export default CryptoIcon;
