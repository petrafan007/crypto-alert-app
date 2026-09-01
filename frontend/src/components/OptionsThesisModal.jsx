import React, { useEffect, useRef, useState } from 'react';
import CloseIcon from '@mui/icons-material/Close';
import './OptionsThesisModal.css';

const TABS = [
  { id: 'assumptions', label: 'Assumptions' },
  { id: 'price', label: 'Option Price Matrix' },
  { id: 'pnl', label: 'P&L Matrix' },
  { id: 'combined', label: 'Combined View' },
];

function formatCurrency(value, maximumFractionDigits = 2) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: maximumFractionDigits,
    maximumFractionDigits,
  }).format(Number(value) || 0);
}

function formatPercent(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value) || 0);
}

function formatDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  return new Intl.DateTimeFormat('en-US', options).format(new Date(`${value}T12:00:00`));
}

function formatValue(item) {
  if (item.format === 'currency') return formatCurrency(item.value);
  if (item.format === 'percent') return formatPercent(item.value);
  if (item.format === 'date') return formatDate(item.value);
  if (item.format === 'text') return String(item.value || 'Unavailable');
  return new Intl.NumberFormat('en-US').format(Number(item.value) || 0);
}

function formatPnl(value, maximumFractionDigits = 2) {
  const numericValue = Number(value) || 0;
  const formattedValue = formatCurrency(Math.abs(numericValue), maximumFractionDigits);
  if (numericValue > 0) return `+${formattedValue}`;
  if (numericValue < 0) return `-${formattedValue}`;
  return formattedValue;
}

function MatrixTable({ thesis, mode }) {
  const isPnl = mode === 'pnl';
  const isCombined = mode === 'combined';
  const label = isPnl ? 'P&L Matrix' : isCombined ? 'Combined View' : 'Option Price Matrix';

  return (
    <div className="thesis-matrix-scroll" tabIndex="0" aria-label={`${label} scenario table`}>
      <table className={`thesis-matrix thesis-matrix-${mode}`}>
        <thead>
          <tr>
            <th scope="col">Move</th>
            <th scope="col">Underlying</th>
            {thesis.columns.map((column) => (
              <th scope="col" key={`${column.date}-${column.dte}`}>
                <span>{formatDate(column.date, { month: 'short', day: 'numeric' })}</span>
                <small>{column.dte} DTE</small>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {thesis.rows.map((row) => (
            <tr key={row.percent_change} className={row.percent_change === 0 ? 'thesis-baseline-row' : ''}>
              <th scope="row" className={row.percent_change > 0 ? 'thesis-positive-move' : row.percent_change < 0 ? 'thesis-negative-move' : ''}>
                <span>{formatPercent(row.percent_change)}</span>
                {row.reference_levels?.map((label) => (
                  <small className="thesis-reference-level" key={label}>{label}</small>
                ))}
              </th>
              <td className="thesis-underlying-price">{formatCurrency(row.underlying_price)}</td>
              {thesis.columns.map((column, index) => {
                const optionPrice = row.option_prices[index];
                const pnl = row.pnl[index];
                if (isCombined) {
                  return (
                    <td key={`${column.date}-${column.dte}`} className={`thesis-combined-cell ${pnl > 0 ? 'thesis-profit-cell' : pnl < 0 ? 'thesis-loss-cell' : ''}`}>
                      <span>{formatCurrency(optionPrice)}</span>
                      <small>{formatPnl(pnl, 0)}</small>
                    </td>
                  );
                }
                const value = isPnl ? pnl : optionPrice;
                return (
                  <td key={`${column.date}-${column.dte}`} className={isPnl && value > 0 ? 'thesis-profit-cell' : isPnl && value < 0 ? 'thesis-loss-cell' : ''}>
                    {isPnl ? formatPnl(value) : formatCurrency(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OptionsThesisModal({ isOpen, onClose, thesis, loading, error, onRetry }) {
  const [activeTab, setActiveTab] = useState('assumptions');
  const closeButtonRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    closeButtonRef.current?.focus();
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) setActiveTab('assumptions');
  }, [isOpen]);

  if (!isOpen) return null;

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) onClose();
  };

  return (
    <div className="options-thesis-modal-overlay" onMouseDown={handleBackdropClick}>
      <section className="options-thesis-modal" role="dialog" aria-modal="true" aria-labelledby="options-thesis-title">
        <header className="options-thesis-modal-header">
          <div>
            <p className="options-thesis-eyebrow">Scenario Thesis</p>
            <h2 id="options-thesis-title">
              {thesis ? `${thesis.underlying_symbol} ${thesis.option_type} analysis` : 'Option analysis'}
            </h2>
          </div>
          <button ref={closeButtonRef} type="button" className="options-thesis-close" onClick={onClose} aria-label="Close thesis viewer" title="Close">
            <CloseIcon fontSize="small" />
          </button>
        </header>

        {loading && (
          <div className="options-thesis-state" role="status">
            <span className="options-thesis-spinner" aria-hidden="true" />
            <p>Building your scenario thesis...</p>
          </div>
        )}

        {error && !loading && (
          <div className="options-thesis-state options-thesis-error" role="alert">
            <p>{error}</p>
            <button type="button" className="btn btn-sm btn-primary" onClick={onRetry}>Try again</button>
          </div>
        )}

        {thesis && !loading && !error && (
          <>
            <div className="options-thesis-context">
              <span>{thesis.option_type}</span>
              <span>{formatCurrency(thesis.assumptions[1].value)} strike</span>
              <span>{thesis.rows.length} scenarios</span>
              <span>{thesis.columns.length} valuation dates</span>
              <span>±{formatPercent(thesis.scenario_range_percent)} spot range</span>
            </div>
            <div className="options-thesis-tabs" role="tablist" aria-label="Thesis views">
              {TABS.map((tab) => (
                <button
                  type="button"
                  role="tab"
                  key={tab.id}
                  id={`options-thesis-tab-${tab.id}`}
                  aria-controls={`options-thesis-panel-${tab.id}`}
                  aria-selected={activeTab === tab.id}
                  className={activeTab === tab.id ? 'active' : ''}
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="options-thesis-panel" id={`options-thesis-panel-${activeTab}`} role="tabpanel" aria-labelledby={`options-thesis-tab-${activeTab}`}>
              {activeTab === 'assumptions' && (
                <>
                  <div className="options-thesis-outputs">
                    {thesis.key_outputs.map((item) => (
                      <div className="options-thesis-output" key={item.label}>
                        <span>{item.label}</span>
                        <strong>{formatValue(item)}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="options-thesis-assumptions">
                    {thesis.assumptions.map((item) => (
                      <div className="options-thesis-assumption" key={item.label}>
                        <span>{item.label}</span>
                        <strong>{formatValue(item)}</strong>
                        <small>{item.units}</small>
                        <p>{item.note}</p>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {activeTab === 'price' && <MatrixTable thesis={thesis} mode="price" />}
              {activeTab === 'pnl' && <MatrixTable thesis={thesis} mode="pnl" />}
              {activeTab === 'combined' && <MatrixTable thesis={thesis} mode="combined" />}
            </div>
          </>
        )}
      </section>
    </div>
  );
}