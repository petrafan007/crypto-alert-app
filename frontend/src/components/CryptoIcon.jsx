import React, { useState } from 'react';
import './CryptoIcon.css';

// Embedded SVGs for instant zero-latency rendering of major coins
const COIN_SVGS = {
  BTC: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#F7931A"/>
      <path d="M22.8 13.5c.3-2-1.2-3.1-3.3-3.8l.7-2.7-1.6-.4-.7 2.6c-.4-.1-.9-.2-1.3-.3l.7-2.7-1.6-.4-.7 2.7c-.3-.1-.7-.2-1.1-.2l-2.3-.6-.4 1.8s1.2.3 1.2.3c.7.2.8.6.8.9l-.8 3.3c.1 0 .2 0 .3.1l-.3-.1-1.1 4.6c-.1.2-.3.6-.8.4 0 0-1.2-.3-1.2-.3l-.9 2 2.1.5c.4.1.8.2 1.1.3l-.7 2.8 1.6.4.7-2.8c.4.1.9.2 1.3.3l-.7 2.8 1.6.4.7-2.7c2.8.5 4.9.3 5.8-2.2.7-2-.1-3.2-1.5-3.9 1.1-.3 1.9-1 2.1-2.5zm-3.8 5.4c-.5 2-3.9.9-5 .6l.9-3.6c1.1.3 4.6.8 4.1 3zm.5-5.5c-.5 1.8-3.3.9-4.2.7l.8-3.3c.9.2 3.8.7 3.4 2.6z" fill="#FFF"/>
    </svg>
  ),
  ETH: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#627EEA"/>
      <g fill="#FFF" fillRule="nonzero">
        <path fillOpacity=".6" d="M16.498 4v8.87l7.497 3.35z"/>
        <path d="M16.498 4L9 16.22l7.498-3.35z"/>
        <path fillOpacity=".6" d="M16.498 21.968v6.027L24 17.616z"/>
        <path d="M16.498 27.995v-6.028L9 17.616z"/>
        <path fillOpacity=".2" d="M16.498 20.573l7.497-4.353-7.497-3.348z"/>
        <path fillOpacity=".6" d="M9 16.22l7.498 4.353v-7.701z"/>
      </g>
    </svg>
  ),
  SOL: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#000"/>
      <path d="M8.2 21.8c.1-.1.3-.2.5-.2h14.7c.3 0 .5.3.4.6l-1.6 3.2c-.1.1-.3.2-.5.2H7c-.3 0-.5-.3-.4-.6l1.6-3.2zm0-12.4c.1-.1.3-.2.5-.2h14.7c.3 0 .5.3.4.6L22.2 13c-.1.1-.3.2-.5.2H7c-.3 0-.5-.3-.4-.6l1.6-3.2zm15.2 6.2c-.1.1-.3.2-.5.2H8.2c-.3 0-.5-.3-.4-.6l1.6-3.2c.1-.1.3-.2.5-.2h14.7c.3 0 .5.3.4.6l-1.6 3.2z" fill="url(#sol_grad)"/>
      <defs>
        <linearGradient id="sol_grad" x1="6.8" y1="25.6" x2="23.8" y2="9.2" gradientUnits="userSpaceOnUse">
          <stop stopColor="#00FFA3"/>
          <stop offset="1" stopColor="#DC1FFF"/>
        </linearGradient>
      </defs>
    </svg>
  ),
  XRP: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#23292F"/>
      <path d="M23.9 8h2.3l-5.6 5.5c-2.5 2.5-6.6 2.5-9.1 0L5.8 8h2.4l4.5 4.4c1.8 1.8 4.7 1.8 6.5 0L23.9 8zM8.1 24H5.8l5.6-5.5c2.5-2.5 6.6-2.5 9.1 0l5.6 5.5h-2.3l-4.5-4.4c-1.8-1.8-4.7-1.8-6.5 0L8.1 24z" fill="#FFF"/>
    </svg>
  ),
  ADA: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#0033AD"/>
      <circle cx="16" cy="16" r="3" fill="#FFF"/>
      <circle cx="16" cy="9" r="1.5" fill="#FFF"/>
      <circle cx="16" cy="23" r="1.5" fill="#FFF"/>
      <circle cx="9.5" cy="12.5" r="1.5" fill="#FFF"/>
      <circle cx="22.5" cy="12.5" r="1.5" fill="#FFF"/>
      <circle cx="9.5" cy="19.5" r="1.5" fill="#FFF"/>
      <circle cx="22.5" cy="19.5" r="1.5" fill="#FFF"/>
    </svg>
  ),
  DOGE: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#C2A633"/>
      <path d="M12 9h5.5c3.6 0 6.5 2.9 6.5 7s-2.9 7-6.5 7H12V9zm3.5 11h2c2 0 3.5-1.6 3.5-4s-1.5-4-3.5-4h-2v8z" fill="#FFF"/>
      <path d="M10 15h9v2h-9z" fill="#FFF"/>
    </svg>
  ),
  AVAX: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#E84142"/>
      <path d="M16 7l8.5 15h-4.3L16 14.5l-4.2 7.5H7.5L16 7z" fill="#FFF"/>
    </svg>
  ),
  DOT: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#E6007A"/>
      <ellipse cx="16" cy="14" rx="7" ry="6" fill="#FFF"/>
      <circle cx="16" cy="24" r="2.5" fill="#FFF"/>
    </svg>
  ),
  LINK: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#375BD2"/>
      <path d="M16 6.5l-7.8 4.5v9l7.8 4.5 7.8-4.5v-9L16 6.5zm5.2 12l-5.2 3-5.2-3v-6l5.2-3 5.2 3v6z" fill="#FFF"/>
    </svg>
  ),
  LTC: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#A6A9AA"/>
      <path d="M13.5 7h4v11.5l3.5-.8-.7 3.3-2.8.6v2.4h7v4h-11V7zm-2.2 8.5l1-.2 1.3-4.2h3.3l-1.3 4.2 2.5-.5-.6 2.5-2.6.5-1.1 3.5h-3.3l1.1-3.5-1.7.3.4-2.6z" fill="#FFF"/>
    </svg>
  ),
  BNB: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#F3BA2F"/>
      <path d="M16 6.5l3.5 3.5-3.5 3.5-3.5-3.5L16 6.5zm-5.5 5.5l3.5 3.5L10.5 19 7 15.5l3.5-3.5zm11 0l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zM16 15.5l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zm0 9l3.5-3.5 3.5 3.5L16 28l-7-3.5 3.5-3.5 3.5 3.5z" fill="#FFF"/>
    </svg>
  ),
  USDT: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#26A17B"/>
      <path d="M17.8 15.6v-.1c2.4-.1 4.2-.6 4.2-1.2 0-.6-1.8-1.1-4.2-1.2v-2.3h6v-2.5H8.2v2.5h6v2.3c-2.4.1-4.2.6-4.2 1.2 0 .6 1.8 1.1 4.2 1.2v7.1h3.6v-7.1zm-1.8-.8c-2.7 0-4.8-.4-4.8-.9s2.1-.9 4.8-.9 4.8.4 4.8.9-2.1.9-4.8.9z" fill="#FFF"/>
    </svg>
  ),
  USDC: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#2775CA"/>
      <path d="M16 7.5A8.5 8.5 0 1024.5 16 8.5 8.5 0 0016 7.5zm0 15a6.5 6.5 0 116.5-6.5 6.5 6.5 0 01-6.5 6.5z" fill="#FFF"/>
      <path d="M17.2 12.5a2.5 2.5 0 00-2.4 1.8.8.8 0 01-1-.4.8.8 0 01.4-1 4.1 4.1 0 013-1.8v-1.1h1.6v1.1a4.2 4.2 0 012.8 1.6 4.1 4.1 0 01.3 4.9 3.5 3.5 0 01-2.9 1.5 2.3 2.3 0 00-2.3 2.3c0 1.2 1 2.2 2.3 2.2a2.5 2.5 0 002.4-1.8.8.8 0 011 .4.8.8 0 01-.4 1 4.1 4.1 0 01-3 1.8v1.1h-1.6v-1.1a4.2 4.2 0 01-2.8-1.6 4.1 4.1 0 01-.3-4.9 3.5 3.5 0 012.9-1.5 2.3 2.3 0 002.3-2.3c0-1.2-1-2.2-2.3-2.2z" fill="#FFF"/>
    </svg>
  ),
  ONT: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#00A6C4"/>
      <path d="M16 8a8 8 0 108 8h-4a4 4 0 11-4-4V8z" fill="#FFF"/>
    </svg>
  ),
  MATIC: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#8247E5"/>
      <path d="M21.5 13.2l-3.8-2.2a1.8 1.8 0 00-1.8 0l-3.8 2.2a1.8 1.8 0 00-.9 1.5v4.4a1.8 1.8 0 00.9 1.5l3.8 2.2a1.8 1.8 0 001.8 0l3.8-2.2a1.8 1.8 0 00.9-1.5v-4.4a1.8 1.8 0 00-.9-1.5zm-5.5 7.4l-2.7-1.6v-3.1l2.7 1.6v3.1zm1.6-4.6l-2.7-1.6 2.7-1.6 2.7 1.6-2.7 1.6zm3.9 3.1l-2.7 1.6v-3.1l2.7-1.6v3.1z" fill="#FFF"/>
    </svg>
  ),
  POL: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#8247E5"/>
      <path d="M21.5 13.2l-3.8-2.2a1.8 1.8 0 00-1.8 0l-3.8 2.2a1.8 1.8 0 00-.9 1.5v4.4a1.8 1.8 0 00.9 1.5l3.8 2.2a1.8 1.8 0 001.8 0l3.8-2.2a1.8 1.8 0 00.9-1.5v-4.4a1.8 1.8 0 00-.9-1.5z" fill="#FFF"/>
    </svg>
  ),
  NEAR: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#000000"/>
      <path d="M10 22V10l8.5 10.5h.5V10h3v12L13.5 11.5h-.5V22h-3z" fill="#FFF"/>
    </svg>
  ),
  SUI: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#2A82E4"/>
      <path d="M16 6c-3 4-7 10-7 14a7 7 0 0014 0c0-4-4-10-7-14z" fill="#FFF"/>
    </svg>
  ),
  XLM: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#14B6EB"/>
      <path d="M24 10l-14 9M8 22l14-9M7 16h18" stroke="#FFF" strokeWidth="2.5" strokeLinecap="round"/>
    </svg>
  ),
  TRX: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#EF0027"/>
      <path d="M7 8l18 4-9 14L7 8zm4 3l6 9 4-10-10 1z" fill="#FFF"/>
    </svg>
  ),
  SHIB: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#FFA409"/>
      <path d="M16 8l4 6h-8l4-6zm-6 8l-2 5 5-2-3-3zm12 0l3 3-5 2 2-5zm-6 2l-3 4h6l-3-4z" fill="#FFF"/>
    </svg>
  ),
  UNI: (
    <svg viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#FF007A"/>
      <path d="M12 9c2-2 6-2 8 0s2 6 0 8l-4 5-4-5c-2-2-2-6 0-8z" fill="#FFF"/>
    </svg>
  )
};

// Deterministic pastel color for coins without icons
const getColorForSymbol = (sym) => {
  let hash = 0;
  for (let i = 0; i < sym.length; i++) {
    hash = sym.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash % 360);
  return `hsl(${hue}, 65%, 45%)`;
};

export const CryptoIcon = ({ symbol, size = 20, className = '' }) => {
  const [imgError, setImgError] = useState(false);
  
  if (!symbol) return null;
  
  // Clean symbol string (remove USDT, USD, /USDT, spaces)
  let cleanSym = String(symbol).toUpperCase().trim();
  if (cleanSym.endsWith('USDT') && cleanSym.length > 4) cleanSym = cleanSym.replace(/USDT$/, '');
  if (cleanSym.endsWith('USD') && cleanSym.length > 3) cleanSym = cleanSym.replace(/USD$/, '');
  if (cleanSym.includes('/')) cleanSym = cleanSym.split('/')[0];
  
  // 1. Direct SVG embed match
  if (COIN_SVGS[cleanSym]) {
    return (
      <span 
        className={`crypto-coin-icon-wrapper ${className}`}
        style={{ width: `${size}px`, height: `${size}px`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
      >
        {COIN_SVGS[cleanSym]}
      </span>
    );
  }
  
  // 2. High quality CDN icon with error fallback
  const cdnUrl = `https://cdn.jsdelivr.net/gh/atomiclabs/cryptocurrency-icons@1a63539be16e3369b1813821e2f7b7629d900593/svg/color/${cleanSym.toLowerCase()}.svg`;
  
  if (!imgError) {
    return (
      <span 
        className={`crypto-coin-icon-wrapper ${className}`}
        style={{ width: `${size}px`, height: `${size}px`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
      >
        <img 
          src={cdnUrl}
          alt={cleanSym}
          width={size}
          height={size}
          className="crypto-coin-img"
          onError={() => setImgError(true)}
          loading="lazy"
        />
      </span>
    );
  }
  
  // 3. Fallback Initial Badge
  const bgColor = getColorForSymbol(cleanSym);
  return (
    <span 
      className={`crypto-coin-fallback-badge ${className}`}
      style={{ 
        width: `${size}px`, 
        height: `${size}px`, 
        fontSize: `${Math.max(9, Math.floor(size * 0.45))}px`,
        backgroundColor: bgColor 
      }}
      title={cleanSym}
    >
      {cleanSym.slice(0, 3)}
    </span>
  );
};

export const BinanceLogo = ({ size = 28, style = {} }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    style={{ verticalAlign: 'middle', display: 'inline-block', flexShrink: 0, ...style }}
  >
    <circle cx="16" cy="16" r="16" fill="#F3BA2F" />
    <path
      d="M16 6.5l3.5 3.5-3.5 3.5-3.5-3.5L16 6.5zm-5.5 5.5l3.5 3.5L10.5 19 7 15.5l3.5-3.5zm11 0l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zM16 15.5l3.5 3.5-3.5 3.5-3.5-3.5 3.5-3.5zm0 9l3.5-3.5 3.5 3.5L16 28l-7-3.5 3.5-3.5 3.5 3.5z"
      fill="#FFF"
    />
  </svg>
);

export const WebullLogo = ({ size = 28, style = {} }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    fill="none"
    style={{ verticalAlign: 'middle', display: 'inline-block', flexShrink: 0, ...style }}
  >
    <rect width="48" height="48" rx="10" fill="#205BFF" />
    <path
      d="M13 18C13 18 16 28 20 28C24 28 24 21 24 21C24 21 24 28 28 28C32 28 35 18 35 18C35 18 31 22 28 22C25 22 25 16 25 16H23C23 16 23 22 20 22C17 22 13 18 13 18Z"
      fill="white"
    />
  </svg>
);

export default CryptoIcon;
