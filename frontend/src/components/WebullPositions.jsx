import React, { useMemo, useState } from 'react';
import FilterListIcon from '@mui/icons-material/FilterList';
import ViewColumnOutlinedIcon from '@mui/icons-material/ViewColumnOutlined';
import CloseIcon from '@mui/icons-material/Close';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import './WebullPositions.css';

const DEFAULT_COLUMNS = [
  'symbol', 'quantity', 'market_value', 'mark', 'average_price',
  'last', 'day_pnl', 'day_pnl_pct', 'open_pnl', 'open_pnl_pct',
];

const COLUMN_DEFINITIONS = [
  { id: 'symbol', label: 'Symbol', type: 'symbol', locked: true },
  { id: 'quantity', label: 'Quantity', type: 'number' },
  { id: 'market_value', label: 'Market value', type: 'currency' },
  { id: 'mark', label: 'Mark', type: 'currency' },
  { id: 'average_price', label: 'Average price', type: 'currency' },
  { id: 'last', label: 'Last', type: 'currency' },
  { id: 'day_pnl', label: '1D open P&L', type: 'pnl' },
  { id: 'day_pnl_pct', label: '1D open P&L %', type: 'pnl_percent' },
  { id: 'open_pnl', label: 'Open P&L', type: 'pnl' },
  { id: 'open_pnl_pct', label: 'Open P&L %', type: 'pnl_percent' },
  { id: 'bid', label: 'Bid', type: 'currency' },
  { id: 'ask', label: 'Ask', type: 'currency' },
  { id: 'bid_size', label: 'Bid size', type: 'number' },
  { id: 'ask_size', label: 'Ask size', type: 'number' },
  { id: 'dte', label: 'Days to expiration', type: 'number' },
  { id: 'delta', label: 'Delta', type: 'decimal' },
  { id: 'gamma', label: 'Gamma', type: 'decimal' },
  { id: 'theta', label: 'Theta', type: 'decimal' },
  { id: 'vega', label: 'Vega', type: 'decimal' },
  { id: 'rho', label: 'Rho', type: 'decimal' },
  { id: 'implied_volatility', label: 'Implied volatility', type: 'volatility' },
  { id: 'underlying_symbol', label: 'Underlying', type: 'text' },
  { id: 'asset_type', label: 'Asset type', type: 'text' },
  { id: 'expiration_date', label: 'Expiration date', type: 'date' },
  { id: 'strike', label: 'Strike', type: 'currency' },
  { id: 'contract_type', label: 'Contract type', type: 'text' },
  { id: 'underlying_price', label: 'Underlying price', type: 'currency' },
  { id: 'iv_rank', label: 'IV rank', type: 'volatility' },
  { id: 'iv_52_week_high', label: 'IV 52 week high', type: 'volatility' },
  { id: 'iv_52_week_low', label: 'IV 52 week low', type: 'volatility' },
  { id: 'historical_volatility', label: 'Historical volatility', type: 'volatility' },
  { id: 'days_to_last_trade', label: 'Days to last day to trade', type: 'number' },
  { id: 'last_trade_date', label: 'Last day to trade', type: 'date' },
  { id: 'settlement_type', label: 'Settlement type', type: 'text' },
];

const COLUMN_MAP = new Map(COLUMN_DEFINITIONS.map((column) => [column.id, column]));
const STORAGE_KEY = 'webull-positions-columns-v1';

function firstValue(position, ...keys) {
  for (const key of keys) {
    const value = position?.[key];
    if (value !== null && value !== undefined && value !== '') return value;
  }
  return null;
}

function numericValue(position, ...keys) {
  const value = firstValue(position, ...keys);
  if (value === null) return null;
  const parsed = Number(String(value).replace(/[,$%]/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function assetType(position) {
  const value = String(position?.instrument_type || position?.asset_type || 'Security').toUpperCase();
  if (value.includes('OPTION')) return 'Options';
  if (/CRYPTO|COIN|TOKEN/.test(value)) return 'Crypto';
  if (value.includes('FUTURE')) return 'Futures';
  if (/EQUITY|STOCK|ETF/.test(value)) return 'Equities';
  if (value === 'CASH') return 'Cash';
  if (value.includes('EVENT')) return 'Event Contracts';
  return value.charAt(0) + value.slice(1).toLowerCase();
}

function optionExpiration(position) {
  return firstValue(position, 'option_expiration', 'expiration_date', 'expiry_date');
}

function daysToDate(value) {
  if (!value) return null;
  const target = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  const current = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12);
  return Math.max(0, Math.ceil((target.getTime() - current.getTime()) / 86400000));
}

function positionDte(position) {
  return numericValue(position, 'days_to_expiration', 'dte') ?? daysToDate(optionExpiration(position));
}

function valueForColumn(position, columnId) {
  switch (columnId) {
    case 'symbol': return String(position.symbol || position.underlying_symbol || '—').toUpperCase();
    case 'quantity': return numericValue(position, 'quantity', 'amount');
    case 'market_value': return numericValue(position, 'current_value', 'market_value');
    case 'mark': return numericValue(position, 'mark', 'mark_price', 'current_price', 'last_price');
    case 'average_price': return numericValue(position, 'average_price', 'avg_entry', 'cost_price');
    case 'last': return numericValue(position, 'last_price', 'current_price');
    case 'day_pnl': return numericValue(position, 'day_profit_loss', 'day_pnl', 'today_profit_loss', 'todays_return');
    case 'day_pnl_pct': return numericValue(position, 'day_profit_loss_rate', 'day_pnl_pct', 'today_profit_loss_rate', 'todays_return_pct');
    case 'open_pnl': return numericValue(position, 'webull_unrealized_pnl', 'unrealized_profit_loss', 'unrealized_pnl');
    case 'open_pnl_pct': return numericValue(position, 'unrealized_profit_loss_rate', 'open_pnl_pct', 'pct_change');
    case 'bid': return numericValue(position, 'bid', 'bid_price');
    case 'ask': return numericValue(position, 'ask', 'ask_price');
    case 'bid_size': return numericValue(position, 'bid_size', 'bidSize');
    case 'ask_size': return numericValue(position, 'ask_size', 'askSize');
    case 'dte': return positionDte(position);
    case 'delta': return numericValue(position, 'delta');
    case 'gamma': return numericValue(position, 'gamma');
    case 'theta': return numericValue(position, 'theta');
    case 'vega': return numericValue(position, 'vega');
    case 'rho': return numericValue(position, 'rho');
    case 'implied_volatility': return numericValue(position, 'implied_volatility', 'iv');
    case 'underlying_symbol': return firstValue(position, 'underlying_symbol', 'underlying');
    case 'asset_type': return assetType(position);
    case 'expiration_date': return optionExpiration(position);
    case 'strike': return numericValue(position, 'option_strike', 'strike_price', 'strike');
    case 'contract_type': return firstValue(position, 'option_type', 'contract_type', 'put_call');
    case 'underlying_price': return numericValue(position, 'underlying_price');
    case 'iv_rank': return numericValue(position, 'iv_rank');
    case 'iv_52_week_high': return numericValue(position, 'iv_52_week_high', 'iv52_week_high');
    case 'iv_52_week_low': return numericValue(position, 'iv_52_week_low', 'iv52_week_low');
    case 'historical_volatility': return numericValue(position, 'historical_volatility');
    case 'days_to_last_trade': return numericValue(position, 'days_to_last_trade') ?? daysToDate(firstValue(position, 'last_trade_date'));
    case 'last_trade_date': return firstValue(position, 'last_trade_date');
    case 'settlement_type': return firstValue(position, 'settlement_type');
    default: return null;
  }
}

function formatNumber(value, maximumFractionDigits = 6) {
  if (value === null) return '—';
  return Number(value).toLocaleString('en-US', { maximumFractionDigits });
}

function formatCurrency(value) {
  if (value === null) return '—';
  const digits = Math.abs(value) < 1 ? 4 : 2;
  return Number(value).toLocaleString('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatVolatility(value) {
  if (value === null) return '—';
  const percent = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percent.toFixed(2)}%`;
}

function formatCell(value, type) {
  if (value === null || value === undefined || value === '') return '—';
  if (type === 'currency') return formatCurrency(value);
  if (type === 'number') return formatNumber(value);
  if (type === 'decimal') return Number(value).toFixed(4);
  if (type === 'volatility') return formatVolatility(value);
  if (type === 'date') return formatDate(value);
  return String(value);
}

function optionSymbol(position) {
  const symbol = String(position.symbol || position.underlying_symbol || '—').toUpperCase();
  if (assetType(position) !== 'Options') return symbol;
  const expiration = optionExpiration(position);
  const strike = valueForColumn(position, 'strike');
  const contractType = String(valueForColumn(position, 'contract_type') || '').toLowerCase();
  const dateLabel = expiration ? new Date(`${String(expiration).slice(0, 10)}T12:00:00`).toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' }) : '';
  return [position.underlying_symbol || symbol, dateLabel, strike === null ? '' : `$${formatNumber(strike, 4)}`, contractType ? contractType.charAt(0).toUpperCase() + contractType.slice(1) : ''].filter(Boolean).join(' ');
}

function initialColumnState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    const validOrder = Array.isArray(saved?.order) ? saved.order.filter((id) => COLUMN_MAP.has(id)) : [];
    const order = [...validOrder, ...COLUMN_DEFINITIONS.map((column) => column.id).filter((id) => !validOrder.includes(id))];
    const selected = Array.isArray(saved?.selected) ? saved.selected.filter((id) => COLUMN_MAP.has(id)) : DEFAULT_COLUMNS;
    return { order, selected: selected.includes('symbol') ? selected : ['symbol', ...selected] };
  } catch {
    return { order: COLUMN_DEFINITIONS.map((column) => column.id), selected: DEFAULT_COLUMNS };
  }
}

export default function WebullPositions({ positions, isTestMode = false }) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [assetFilter, setAssetFilter] = useState('All');
  const [dteFilter, setDteFilter] = useState(null);
  const [columnState, setColumnState] = useState(initialColumnState);
  const [sort, setSort] = useState({ id: 'symbol', direction: 'asc' });
  const [draggedColumn, setDraggedColumn] = useState(null);
  const securityPositions = useMemo(
    () => positions.filter((position) => assetType(position) !== 'Cash'),
    [positions],
  );

  const updateColumnState = (nextState) => {
    setColumnState(nextState);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
  };

  const visibleColumns = columnState.order.filter((id) => columnState.selected.includes(id)).map((id) => COLUMN_MAP.get(id));
  const filteredPositions = useMemo(() => securityPositions
    .filter((position) => assetFilter === 'All' || assetType(position) === assetFilter)
    .filter((position) => dteFilter === null || (positionDte(position) !== null && positionDte(position) <= dteFilter))
    .sort((left, right) => {
      const leftValue = valueForColumn(left, sort.id);
      const rightValue = valueForColumn(right, sort.id);
      if ((leftValue === null || leftValue === undefined) && (rightValue === null || rightValue === undefined)) return 0;
      if (leftValue === null || leftValue === undefined) return 1;
      if (rightValue === null || rightValue === undefined) return -1;
      const comparison = typeof leftValue === 'number' && typeof rightValue === 'number'
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue));
      return sort.direction === 'asc' ? comparison : -comparison;
    }), [securityPositions, assetFilter, dteFilter, sort]);

  const toggleSort = (id) => setSort((current) => ({
    id,
    direction: current.id === id && current.direction === 'asc' ? 'desc' : 'asc',
  }));

  const toggleColumn = (id) => {
    const column = COLUMN_MAP.get(id);
    if (column?.locked) return;
    const selected = columnState.selected.includes(id)
      ? columnState.selected.filter((columnId) => columnId !== id)
      : [...columnState.selected, id];
    updateColumnState({ ...columnState, selected });
  };

  const moveColumn = (targetId) => {
    if (!draggedColumn || draggedColumn === targetId) return;
    const order = columnState.order.filter((id) => id !== draggedColumn);
    order.splice(order.indexOf(targetId), 0, draggedColumn);
    updateColumnState({ ...columnState, order });
    setDraggedColumn(null);
  };

  const resetFilters = () => {
    setAssetFilter('All');
    setDteFilter(null);
  };

  return (
    <section className="webull-positions">
      <header className="webull-positions-header">
        <div>
          <h2>Positions</h2>
          <p>{filteredPositions.length} of {securityPositions.length} positions{isTestMode ? ' in Test Mode' : ''}</p>
        </div>
        <div className="webull-positions-actions">
          <button type="button" onClick={() => setFilterOpen(true)} className={assetFilter !== 'All' || dteFilter !== null ? 'active' : ''}>
            <FilterListIcon fontSize="small" /> Filter
          </button>
          <button type="button" onClick={() => setColumnsOpen(true)}>
            <ViewColumnOutlinedIcon fontSize="small" /> Customize columns
          </button>
        </div>
      </header>

      {!securityPositions.length ? (
        <div className="empty-state"><p>{isTestMode ? 'No simulated positions yet.' : 'No imported Webull positions are available.'}</p></div>
      ) : !filteredPositions.length ? (
        <div className="empty-state"><p>No positions match the selected filters.</p><button type="button" className="btn btn-sm btn-secondary" onClick={resetFilters}>Reset filters</button></div>
      ) : (
        <div className="webull-positions-table-wrap">
          <table className="webull-positions-table">
            <thead>
              <tr>
                {visibleColumns.map((column) => (
                  <th key={column.id} scope="col">
                    <button type="button" onClick={() => toggleSort(column.id)}>
                      {column.label}{sort.id === column.id ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredPositions.map((position, index) => (
                <tr key={position.id || `${position.account_id}-${position.symbol}-${index}`}>
                  {visibleColumns.map((column) => {
                    const value = valueForColumn(position, column.id);
                    const isPnl = column.type === 'pnl' || column.type === 'pnl_percent';
                    const pnlClass = isPnl && value > 0 ? 'position-gain' : isPnl && value < 0 ? 'position-loss' : '';
                    return (
                      <td key={column.id} className={`${column.id === 'symbol' ? 'position-symbol' : ''} ${pnlClass}`}>
                        {column.type === 'symbol' ? optionSymbol(position) : column.type === 'pnl'
                          ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${formatCurrency(Math.abs(value))}`)
                          : column.type === 'pnl_percent'
                            ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${Math.abs(value).toFixed(2)}%`)
                            : formatCell(value, column.type)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {filterOpen && (
        <div className="positions-panel-overlay" onMouseDown={(event) => event.target === event.currentTarget && setFilterOpen(false)}>
          <div className="positions-filter-panel" role="dialog" aria-modal="true" aria-labelledby="positions-filter-title">
            <div className="positions-panel-title">
              <h3 id="positions-filter-title">Filter</h3>
              <button type="button" onClick={() => setFilterOpen(false)} title="Close" aria-label="Close position filters"><CloseIcon /></button>
            </div>
            <div className="positions-filter-group">
              <h4>Asset type</h4>
              <div className="positions-filter-options">
                {['All', 'Equities', 'Options', 'Crypto', 'Futures'].map((option) => (
                  <button type="button" key={option} className={assetFilter === option ? 'active' : ''} onClick={() => setAssetFilter(option)}>{option}</button>
                ))}
              </div>
            </div>
            <div className="positions-filter-group">
              <h4>Days to expiration</h4>
              <div className="positions-filter-options">
                {[['All', null], ['≤ 1D', 1], ['≤ 7D', 7], ['≤ 10D', 10], ['≤ 30D', 30]].map(([label, value]) => (
                  <button type="button" key={label} className={dteFilter === value ? 'active' : ''} onClick={() => setDteFilter(value)}>{label}</button>
                ))}
              </div>
            </div>
            <div className="positions-panel-footer">
              <button type="button" onClick={resetFilters}>Reset</button>
              <button type="button" className="primary" onClick={() => setFilterOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {columnsOpen && (
        <div className="positions-panel-overlay positions-columns-overlay" onMouseDown={(event) => event.target === event.currentTarget && setColumnsOpen(false)}>
          <div className="positions-columns-panel" role="dialog" aria-modal="true" aria-labelledby="positions-columns-title">
            <div className="positions-panel-title">
              <div><h3 id="positions-columns-title">Customize columns</h3><p>Drag to reorder. Changes are saved on this device.</p></div>
              <button type="button" onClick={() => setColumnsOpen(false)} title="Close" aria-label="Close column customization"><CloseIcon /></button>
            </div>
            <div className="positions-column-list">
              {columnState.order.map((id) => {
                const column = COLUMN_MAP.get(id);
                return (
                  <div
                    key={id}
                    className="positions-column-option"
                    draggable
                    onDragStart={() => setDraggedColumn(id)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => moveColumn(id)}
                  >
                    <DragIndicatorIcon className="positions-drag-handle" />
                    <span>{column.label}</span>
                    <input type="checkbox" checked={columnState.selected.includes(id)} disabled={column.locked} onChange={() => toggleColumn(id)} aria-label={`Show ${column.label}`} />
                  </div>
                );
              })}
            </div>
            <div className="positions-panel-footer">
              <button type="button" onClick={() => updateColumnState({ order: COLUMN_DEFINITIONS.map((column) => column.id), selected: DEFAULT_COLUMNS })}>Restore defaults</button>
              <button type="button" className="primary" onClick={() => setColumnsOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}