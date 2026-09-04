import React, { useState, useMemo } from 'react';
import './WebullFuturesDiscoverySuite.css';

export const FUTURES_CATEGORIES = [
  { id: 'ALL', name: 'All Products', icon: '🌐' },
  { id: 'INDICES', name: 'Equity Indices', icon: '📈' },
  { id: 'ENERGY', name: 'Energy', icon: '⚡' },
  { id: 'METALS', name: 'Precious Metals', icon: '🪙' },
  { id: 'CRYPTO', name: 'Cryptocurrency', icon: '₿' },
  { id: 'RATES', name: 'Treasuries & Rates', icon: '🏛️' },
];

export default function WebullFuturesDiscoverySuite({
  catalog = { classes: [], products: [] },
  loading = false,
  onRefresh,
  selectedProduct = null,
  onSelectProduct,
  contracts = [],
  selectedContract = null,
  onSelectContract,
  manualInput = '',
  onManualInputChange,
  onLookupManual,
  futuresMessage = '',
  isLightMode = false,
  isMarginAccount = true,
}) {
  const [activeCategory, setActiveCategory] = useState('ALL');
  const [microOnly, setMicroOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const allProducts = useMemo(() => {
    return Array.isArray(catalog?.products) ? catalog.products : [];
  }, [catalog]);

  const filteredProducts = useMemo(() => {
    return allProducts.filter((product) => {
      // Category filter
      if (activeCategory !== 'ALL' && String(product.category || '').toUpperCase() !== activeCategory) {
        return false;
      }
      // Micro contract filter
      if (microOnly && !product.is_micro) {
        return false;
      }
      // Search query filter
      if (searchQuery.trim()) {
        const query = searchQuery.trim().toLowerCase();
        const code = String(product.product_code || product.symbol || '').toLowerCase();
        const name = String(product.name || '').toLowerCase();
        return code.includes(query) || name.includes(query);
      }
      return true;
    });
  }, [allProducts, activeCategory, microOnly, searchQuery]);

  return (
    <div className="futures-discovery-suite" role="region" aria-label="Webull Futures Discovery Suite">
      {/* 1. Header */}
      <div className="futures-discovery-header">
        <div className="futures-title-group">
          <div className="futures-title-icon" aria-hidden="true">🏁</div>
          <div className="futures-title-text">
            <h2>
              Webull Futures Discovery &amp; Selection Suite
              <span className="futures-cme-badge">
                <span className="futures-cme-dot" /> CME Direct Market Access
              </span>
            </h2>
            <p>Select institutional or micro futures products with low intraday margin requirements</p>
          </div>
        </div>

        <div className="futures-header-actions">
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh product catalog from Webull"
          >
            {loading ? 'Refreshing…' : '🔄 Refresh Catalog'}
          </button>
        </div>
      </div>

      {/* Warning if on cash-only account */}
      {!isMarginAccount && (
        <div className="futures-warning-banner" role="alert">
          <span>⚠️ <strong>Margin Account Required:</strong> Webull requires a margin-enabled account to trade US futures. Orders placed on cash accounts will be rejected by Webull.</span>
        </div>
      )}

      {/* Error / info message */}
      {futuresMessage && (
        <div className="futures-warning-banner" role="alert" style={{ background: 'rgba(239, 68, 68, 0.15)', borderColor: 'rgba(239, 68, 68, 0.35)', color: '#fca5a5' }}>
          <span>⚠️ {futuresMessage}</span>
        </div>
      )}

      {/* 2. Category Pills & Filter Controls */}
      <div className="futures-controls-bar">
        <div className="futures-category-pills" role="tablist" aria-label="Futures Categories">
          {FUTURES_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              type="button"
              role="tab"
              aria-selected={activeCategory === cat.id}
              className={`category-pill ${activeCategory === cat.id ? 'active' : ''}`}
              onClick={() => setActiveCategory(cat.id)}
            >
              <span>{cat.icon}</span>
              <span>{cat.name}</span>
            </button>
          ))}

          {/* Micro Contracts Quick Filter */}
          <button
            type="button"
            className={`micro-toggle-pill ${microOnly ? 'active' : ''}`}
            onClick={() => setMicroOnly((prev) => !prev)}
            aria-pressed={microOnly}
            title="Filter to 1/10th size micro futures contracts with reduced margin requirements"
          >
            <span>⚡</span>
            <span>Micro Contracts Only (1/10th Margin)</span>
          </button>
        </div>

        {/* Quick Search & Manual Lookup */}
        <div className="futures-search-box">
          <input
            type="text"
            className="futures-search-input"
            placeholder="Search products (e.g. S&P, Gold)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search futures products"
          />

          <form
            onSubmit={(e) => {
              e.preventDefault();
              onLookupManual?.();
            }}
            className="futures-manual-form"
          >
            <input
              type="text"
              className="futures-manual-input"
              placeholder="Code (ESU26)"
              value={manualInput}
              onChange={(e) => onManualInputChange?.(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
              aria-label="Direct contract code entry"
            />
            <button
              type="submit"
              className="btn btn-sm btn-primary"
              disabled={loading || !manualInput.trim()}
            >
              Find
            </button>
          </form>
        </div>
      </div>

      {/* 3. Product Cards Grid */}
      <div className="futures-products-grid" role="list" aria-label="Futures Products">
        {filteredProducts.map((product) => {
          const isSelected = String(selectedProduct?.product_code || selectedProduct?.symbol || '') === String(product.product_code || product.symbol || '');
          const isMicro = product.is_micro;
          const code = product.product_code || product.symbol;

          return (
            <div
              key={code}
              role="listitem"
              tabIndex={0}
              className={`futures-product-card ${isSelected ? 'selected' : ''}`}
              onClick={() => onSelectProduct?.(product)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectProduct?.(product);
                }
              }}
              aria-label={`${product.name}, ${code}, ${isMicro ? 'Micro contract' : 'Standard contract'}`}
            >
              <div className="product-card-top">
                <div className="product-code-wrap">
                  <span className="product-code">{code}</span>
                  <span className="product-exchange">{product.exchange || 'CME'}</span>
                </div>
                <span className={isMicro ? 'badge-micro' : 'badge-standard'}>
                  {isMicro ? 'MICRO 1/10x' : 'STANDARD'}
                </span>
              </div>

              <div className="product-name" title={product.name}>
                {product.name}
              </div>

              <div className="product-metrics">
                <div className="metric-row">
                  <span>Multiplier:</span>
                  <span className="metric-val-highlight">{product.contract_multiplier ? `$${product.contract_multiplier}` : (product.unit || 'Standard')}</span>
                </div>
                <div className="metric-row">
                  <span>Day Margin:</span>
                  <span className="metric-val-highlight">${Number(product.day_margin || 500).toLocaleString()}</span>
                </div>
                <div className="metric-row">
                  <span>Init Margin:</span>
                  <span className="metric-val-amber">${Number(product.initial_margin || 5000).toLocaleString()}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 4. Active Expiration Chain Selector */}
      {contracts.length > 0 && (
        <div className="futures-expirations-section">
          <div className="expirations-header">
            <span className="expirations-title">
              📅 Active Delivery Months for {selectedProduct?.product_code || selectedContract?.product_code || 'Selected Contract'}
            </span>
            <span style={{ fontSize: '11px', color: '#94a3b8' }}>
              Select an expiration month to load into the chart and ticket
            </span>
          </div>

          <div className="expirations-chain" role="radiogroup" aria-label="Contract Expiration Dates">
            {contracts.map((contract) => {
              const isSelected = selectedContract?.symbol === contract.symbol;
              return (
                <button
                  key={contract.symbol}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  className={`expiration-pill ${isSelected ? 'selected' : ''}`}
                  onClick={() => onSelectContract?.(contract)}
                >
                  <div className="exp-pill-symbol">
                    <span>{contract.symbol}</span>
                    {contract.is_front_month && <span className="exp-front-tag">FRONT</span>}
                  </div>
                  <div className="exp-pill-date">
                    {contract.month_label || contract.expiration_date}
                  </div>
                  <div className="exp-pill-dte">
                    {contract.days_to_expiration != null ? `${contract.days_to_expiration} DTE` : 'Active'}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * WebullFuturesSpecStrip: Contract Specifications & Margin Strip
 * Positioned directly beneath the live interactive chart
 */
export function WebullFuturesSpecStrip({
  selectedContract = null,
  isLightMode = false,
}) {
  if (!selectedContract) return null;

  const dayMargin = selectedContract.day_margin || 500;
  const initialMargin = selectedContract.initial_margin || 5000;
  const tickSize = selectedContract.tick_size || 0.25;
  const tickValue = selectedContract.tick_value || 12.50;
  const multiplier = selectedContract.contract_multiplier || 50;

  return (
    <div className="futures-spec-strip" role="region" aria-label="Futures Contract Specifications">
      <div className="spec-strip-left">
        <span className="spec-contract-badge">{selectedContract.symbol}</span>
        <div className="spec-contract-info">
          <span className="spec-contract-title">{selectedContract.name || 'Webull Futures Contract'}</span>
          <span className="spec-contract-sub">
            {selectedContract.exchange || 'CME'} · Expires {selectedContract.expiration_date || 'Standard Delivery'} {selectedContract.days_to_expiration != null ? `(${selectedContract.days_to_expiration} DTE)` : ''}
          </span>
        </div>
      </div>

      <div className="spec-strip-items">
        <div className="spec-item">
          <span className="spec-item-label">Multiplier</span>
          <span className="spec-item-value">${multiplier} per pt</span>
        </div>
        <div className="spec-item">
          <span className="spec-item-label">Tick Size / Value</span>
          <span className="spec-item-value">{tickSize} pt = ${Number(tickValue).toFixed(2)}</span>
        </div>
        <div className="spec-item">
          <span className="spec-item-label">Day Margin (Est.)</span>
          <span className="spec-item-value spec-margin-day">${Number(dayMargin).toLocaleString()}</span>
        </div>
        <div className="spec-item">
          <span className="spec-item-label">Initial Margin</span>
          <span className="spec-item-value spec-margin-init">${Number(initialMargin).toLocaleString()}</span>
        </div>
        <div className="spec-item">
          <span className="spec-item-label">Trading Hours</span>
          <span className="spec-item-value">23h / Sun-Fri</span>
        </div>
      </div>
    </div>
  );
}
