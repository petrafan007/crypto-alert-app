import React, { useState, useRef, useEffect, useCallback } from 'react';
import axios from 'axios';
import { FaBitcoin, FaDollarSign } from 'react-icons/fa';

/**
 * WatchlistSymbolPicker
 * Search-as-you-type dropdown that finds both crypto and stock/ETF symbols.
 * The user MUST select from the dropdown — no blind text submission.
 *
 * Props:
 *   onSelect({ symbol, asset_type, name }) — called when user picks a result
 *   disabled — disables the input
 *   isLightMode — theme flag
 */
export default function WatchlistSymbolPicker({ onSelect, disabled = false, isLightMode = false }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightedIdx, setHighlightedIdx] = useState(0);
  const inputRef = useRef(null);
  const containerRef = useRef(null);
  const debounceRef = useRef(null);
  const requestIdRef = useRef(0);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => () => clearTimeout(debounceRef.current), []);

  const search = useCallback(async (q) => {
    const requestId = ++requestIdRef.current;
    if (!q || q.length < 1) {
      setResults([]);
      setIsOpen(false);
      return;
    }
    setLoading(true);
    try {
      const res = await axios.get(`/api/watchlist/search-symbol?q=${encodeURIComponent(q)}`, { withCredentials: true });
      if (requestId !== requestIdRef.current) return;
      const items = res.data?.results || [];
      setResults(items);
      setIsOpen(items.length > 0);
      setHighlightedIdx(0);
    } catch {
      if (requestId !== requestIdRef.current) return;
      setResults([]);
      setIsOpen(false);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  const handleInputChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(val.trim()), 280);
  };

  const handleSelect = (item) => {
    setQuery('');
    setResults([]);
    setIsOpen(false);
    onSelect({ symbol: item.symbol, asset_type: item.asset_type, name: item.name });
  };

  const handleKeyDown = (e) => {
    if (!isOpen || results.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightedIdx(i => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightedIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[highlightedIdx]) handleSelect(results[highlightedIdx]);
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const cryptoResults = results.filter(r => r.asset_type === 'crypto');
  const stockResults = results.filter(r => r.asset_type === 'stock');

  const containerStyle = {
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  };

  const inputStyle = {
    flex: 1,
    padding: '9px 14px',
    borderRadius: '8px',
    border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(129,140,248,.4)',
    background: isLightMode ? '#ffffff' : '#0f172a',
    color: isLightMode ? '#0f172a' : '#f8fafc',
    fontSize: '14px',
    outline: 'none',
    fontFamily: 'inherit',
    minWidth: 0,
    width: '100%',
  };

  const dropdownStyle = {
    position: 'absolute',
    top: 'calc(100% + 6px)',
    left: 0,
    right: 0,
    zIndex: 9999,
    background: isLightMode ? '#ffffff' : '#0f172a',
    border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(129,140,248,.35)',
    borderRadius: '10px',
    boxShadow: '0 12px 40px rgba(0,0,0,.35)',
    maxHeight: '320px',
    overflowY: 'auto',
  };

  const groupHeaderStyle = {
    padding: '6px 12px 4px',
    fontSize: '0.7rem',
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: isLightMode ? '#94a3b8' : '#64748b',
    borderTop: isLightMode ? '1px solid #f1f5f9' : '1px solid rgba(255,255,255,.06)',
    marginTop: '4px',
  };

  let globalIdx = 0;

  const renderItem = (item, localIdx, gIdx) => {
    const isCrypto = item.asset_type === 'crypto';
    const isHighlighted = gIdx === highlightedIdx;
    return (
      <div
        key={`${item.asset_type}-${item.symbol}-${localIdx}`}
        onMouseEnter={() => setHighlightedIdx(gIdx)}
        onClick={() => handleSelect(item)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '9px 14px',
          cursor: 'pointer',
          background: isHighlighted
            ? (isLightMode ? '#f1f5f9' : 'rgba(99,102,241,.18)')
            : 'transparent',
          transition: 'background .12s',
        }}
      >
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 24, height: 24, borderRadius: '50%',
          background: isCrypto ? 'rgba(247,147,26,.15)' : 'rgba(34,197,94,.12)',
          color: isCrypto ? '#f7931a' : '#22c55e',
          fontSize: '0.8rem', flexShrink: 0,
        }}>
          {isCrypto ? <FaBitcoin /> : <FaDollarSign />}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: '0.88rem', color: isLightMode ? '#0f172a' : '#f8fafc' }}>
            {item.symbol}
            <span style={{
              marginLeft: 8, fontSize: '0.7rem', fontWeight: 600,
              padding: '1px 6px', borderRadius: '9999px',
              background: isCrypto
                ? (isLightMode ? 'rgba(247,147,26,.15)' : 'rgba(247,147,26,.2)')
                : (isLightMode ? 'rgba(34,197,94,.12)' : 'rgba(34,197,94,.15)'),
              color: isCrypto ? '#f7931a' : '#22c55e',
              letterSpacing: '0.04em',
            }}>
              {isCrypto ? '₿ Crypto' : '$ Stock/ETF'}
            </span>
          </div>
          <div style={{ fontSize: '0.75rem', color: isLightMode ? '#64748b' : '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.display || item.name}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div ref={containerRef} className="watchlist-symbol-picker" style={containerStyle}>
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onFocus={() => results.length > 0 && setIsOpen(true)}
        placeholder="Type a symbol to search (e.g. NVDA, BTC, SPY)..."
        disabled={disabled}
        style={inputStyle}
        aria-label="Search for a symbol to add to watchlist"
        autoComplete="off"
        spellCheck={false}
      />
      {loading && (
        <span style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', fontSize: '0.75rem', color: '#94a3b8', pointerEvents: 'none' }}>
          Searching…
        </span>
      )}
      {isOpen && results.length > 0 && (
        <div style={dropdownStyle}>
          {cryptoResults.length > 0 && (
            <>
              <div style={{ ...groupHeaderStyle, borderTop: 'none', marginTop: 0 }}>
                ₿ Crypto Pairs
              </div>
              {cryptoResults.map((item, idx) => {
                const g = globalIdx++;
                return renderItem(item, idx, g);
              })}
            </>
          )}
          {stockResults.length > 0 && (
            <>
              <div style={groupHeaderStyle}>$ Stocks &amp; ETFs</div>
              {stockResults.map((item, idx) => {
                const g = globalIdx++;
                return renderItem(item, idx, g);
              })}
            </>
          )}
          <div style={{ padding: '6px 12px 8px', fontSize: '0.7rem', color: '#64748b', textAlign: 'center' }}>
            Select a result to add it to your watchlist
          </div>
        </div>
      )}
      {isOpen && !loading && query.length > 0 && results.length === 0 && (
        <div style={{ ...dropdownStyle, padding: '14px', textAlign: 'center', fontSize: '0.85rem', color: '#94a3b8' }}>
          No results for &ldquo;{query}&rdquo;
        </div>
      )}
    </div>
  );
}
