import axios from 'axios';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import FilterListIcon from '@mui/icons-material/FilterList';
import ViewColumnOutlinedIcon from '@mui/icons-material/ViewColumnOutlined';
import CloseIcon from '@mui/icons-material/Close';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import {
  ASSET_VIEWS, COLUMN_MAP, assetType, valueForColumn, formatCell, formatCurrency,
  instrumentName, positionSide, formatTimestamp, defaultColumnState, cleanColumnState,
  moveColumnState, columnStorageKey, mergeEventMarket,
} from '../utils/positions.mjs';
import './WebullPositions.css';

function PositionsDialog({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="positions-dialog" aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="positions-panel-title"><h3>{title}</h3><button type="button" onClick={onClose} aria-label={`Close ${title}`}><CloseIcon /></button></div>
    {children}
  </dialog>;
}

function PositionDetails({ position, onSelectHolding, onOpenEventPosition }) {
  const event = assetType(position) === 'Event Contracts';
  const fields = [
    ['Full symbol', position.symbol], ['Account', valueForColumn(position, 'account')],
    ['Asset type', assetType(position)], ['Side / purchased outcome', positionSide(position)],
    ['Status', valueForColumn(position, 'status')],
    ...(event ? [
      ['Contract / question', instrumentName(position)],
      ['Contract conditions', position.event_rules || position.details?.rules],
      ['Threshold', position.event_threshold ?? position.details?.threshold],
      ['Trading cutoff', formatTimestamp(valueForColumn(position, 'cutoff'))],
      ['Expected settlement', formatTimestamp(position.settlement?.expected_at)],
      ['Confirmed result', position.settlement?.confirmed_outcome],
      ['Last settlement check', formatTimestamp(position.settlement?.last_attempt_at)],
    ] : [
      ['Underlying', valueForColumn(position, 'underlying_symbol')],
      ['Expiration', valueForColumn(position, 'expiration_date')],
      ['Strike', formatCell(valueForColumn(position, 'strike'), 'currency')],
      ['Contract type', valueForColumn(position, 'contract_type')],
      ['Contract multiplier', valueForColumn(position, 'contract_multiplier')],
    ]),
    ['Fees', formatCell(position.fees ?? position.fee, 'currency')],
    ...(position.details?.short && position.details?.long ? [
      ['Short option leg', `${position.details.short.symbol || position.symbol} · ${position.details.short.option_type} · $${position.details.short.strike}`],
      ['Long option leg', `${position.details.long.symbol || position.symbol} · ${position.details.long.option_type} · $${position.details.long.strike}`],
      ['Spread width', formatCell(position.details.width, 'currency')],
    ] : []),
    ...(position.is_quant && ['Options', 'Futures'].includes(assetType(position)) ? [['Valuation basis', 'Allocated collateral plus unrealized P&L']] : []),
    ['Last position update', formatTimestamp(position.updated_at || position.last_updated)],
  ];
  return <><dl className="position-details">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? '—'}</dd></div>)}</dl>
    {(event ? onOpenEventPosition : onSelectHolding) && <button type="button" className="btn btn-secondary" onClick={() => event ? onOpenEventPosition(position) : onSelectHolding(position)}>{event ? 'Open position' : 'Load trade ticket'}</button>}
  </>;
}

export default function WebullPositions({ positions = [], mode = 'REAL', userId, initialAssetView = 'All assets', onSelectHolding, onOpenEventPosition }) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [assetFilter, setAssetFilter] = useState(initialAssetView);
  const [accountFilter, setAccountFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [dteFilter, setDteFilter] = useState(null);
  const [layouts, setLayouts] = useState({});
  const [markets, setMarkets] = useState({});
  const missingSymbols = [...new Set(positions.filter(p => assetType(p) === 'Event Contracts' && (!p.event_title || !p.settlement?.cutoff_at)).map(p => String(p.symbol || '').replace(/ (YES|NO)$/i, '')))].sort().join(',');
  useEffect(() => {
    if (!userId || !missingSymbols) return;
    const controller = new AbortController();
    // Exact held contracts only; serialize requests to respect provider rate limits.
    (async () => {
      for (const symbol of missingSymbols.split(',')) {
        try {
          const { data } = await axios.get('/api/webull/events/markets', { params: { symbol }, withCredentials: true, signal: controller.signal });
          const market = data?.markets?.find(item => item.symbol === symbol);
          if (!market) throw new Error('Contract metadata unavailable');
          if (!controller.signal.aborted) setMarkets(current => ({ ...current, [symbol]: market }));
        } catch {
          if (!controller.signal.aborted) setMarkets(current => ({ ...current, [symbol]: { unavailable: true } }));
        }
        if (controller.signal.aborted) break;
      }
    })();
    return () => controller.abort();
  }, [missingSymbols, userId]);
  const [sort, setSort] = useState({ id: 'symbol', direction: 'asc' });
  const [draggedColumn, setDraggedColumn] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [expanded, setExpanded] = useState(new Set());
  const [, tick] = useState(0);
  const storageKey = columnStorageKey(userId, assetFilter);
  const layoutKey = storageKey || assetFilter;
  useEffect(() => {
    const timer = setInterval(() => tick(n => n + 1), 1000);
    const sync = () => setLayouts({});
    window.addEventListener('storage', sync);
    return () => { clearInterval(timer); window.removeEventListener('storage', sync); };
  }, []);
  const columnState = useMemo(() => {
    if (layouts[layoutKey]) return layouts[layoutKey];
    try { return cleanColumnState(storageKey ? JSON.parse(localStorage.getItem(storageKey)) : null, assetFilter, true); }
    catch { return defaultColumnState(assetFilter, true); }
  }, [layouts, layoutKey, storageKey, assetFilter]);
  const updateColumnState = next => {
    setLayouts(current => ({ ...current, [layoutKey]: next }));
    try { if (storageKey) localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Session layout still works when browser storage is unavailable. */ }
  };
  const securityPositions = useMemo(() => positions.filter(p => assetType(p) !== 'Cash' && Number(p.quantity ?? p.amount ?? 0) !== 0).map(p => mergeEventMarket(p, markets[String(p.symbol || '').replace(/ (YES|NO)$/i, '')])), [positions, markets]);
  const accounts = [...new Map(securityPositions.map(p => [String(p.account_id || p.source || ''), valueForColumn(p, 'account')])).entries()];
  const visibleColumns = columnState.order.filter(id => columnState.selected.includes(id)).map(id => COLUMN_MAP.get(id));
  const filteredPositions = securityPositions
    .filter(p => assetFilter === 'All assets' || assetType(p) === assetFilter)
    .filter(p => accountFilter === 'All' || String(p.account_id || p.source || '') === accountFilter)
    .filter(p => !search || `${p.symbol} ${instrumentName(p)}`.toLowerCase().includes(search.toLowerCase()))
    .filter(p => dteFilter === null || (valueForColumn(p, 'dte') !== null && valueForColumn(p, 'dte') <= dteFilter))
    .sort((a, b) => {
      const left = valueForColumn(a, sort.id), right = valueForColumn(b, sort.id);
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      const comparison = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right));
      return sort.direction === 'asc' ? comparison : -comparison;
    });
  const toggleSort = id => setSort(current => ({ id, direction: current.id === id && current.direction === 'asc' ? 'desc' : 'asc' }));
  const toggleColumn = id => {
    if (COLUMN_MAP.get(id)?.locked) return;
    updateColumnState({ ...columnState, selected: columnState.selected.includes(id) ? columnState.selected.filter(key => key !== id) : [...columnState.selected, id] });
  };
  const endDrag = () => { setDraggedColumn(null); setDropTarget(null); };
  const drop = (event, target) => {
    event.preventDefault();
    updateColumnState(moveColumnState(columnState, draggedColumn, target));
    endDrag();
  };
  const dragProps = id => ({
    onDragOver: event => { if (draggedColumn) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; setDropTarget(id); } },
    onDrop: event => drop(event, id),
  });
  const startDrag = (event, id) => { setDraggedColumn(id); event.dataTransfer.setData('text/plain', id); event.dataTransfer.effectAllowed = 'move'; };
  const resetFilters = () => { setAssetFilter('All assets'); setAccountFilter('All'); setSearch(''); setDteFilter(null); };
  const modeLabel = mode === 'QUANT' ? 'Quantitative Strategy — Paper Positions' : mode === 'TEST' ? 'Test Mode — Paper Positions' : 'Real Trading — Positions';
  const toggleExpanded = key => setExpanded(current => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  return <section className="webull-positions">
    <header className="webull-positions-header">
      <div><h2>Positions</h2><p>{modeLabel} · {filteredPositions.length} of {securityPositions.length} positions</p></div>
      <div className="webull-positions-actions">
        <button type="button" onClick={() => setFilterOpen(true)}><FilterListIcon fontSize="small" /> Filter</button>
        <button type="button" onClick={() => setColumnsOpen(true)}><ViewColumnOutlinedIcon fontSize="small" /> Customize columns</button>
      </div>
    </header>
    <div className="positions-asset-views" role="group" aria-label="Position asset view">
      {ASSET_VIEWS.map(asset => <button key={asset} type="button" aria-pressed={asset === assetFilter} onClick={() => { setAssetFilter(asset); setDteFilter(null); endDrag(); }}>
        {asset} <span>{securityPositions.filter(p => asset === 'All assets' || assetType(p) === asset).length}</span>
      </button>)}
    </div>
    {(accountFilter !== 'All' || search || dteFilter !== null) && <p className="positions-active-filters">Filters: {accountFilter !== 'All' && `${accounts.find(([id]) => id === accountFilter)?.[1] || accountFilter} · `}{search && `“${search}” · `}{dteFilter !== null && `Expiration ≤ ${dteFilter} days · `}<button type="button" onClick={resetFilters}>Reset filters</button></p>}
    {Object.values(markets).some(m => m.unavailable) && <p role="status">Some event contract details are unavailable from Webull. Available saved details are shown.</p>}
    {!filteredPositions.length ? <div className="empty-state"><p>{securityPositions.length ? 'No positions match the selected filters.' : 'No positions available in this mode.'}</p></div> : <div className="webull-positions-table-wrap">
      <table className="webull-positions-table">
        <thead><tr>{visibleColumns.map(column => <th key={column.id} scope="col" aria-sort={sort.id === column.id ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} className={dropTarget === column.id ? 'positions-drop-target' : ''} {...dragProps(column.id)}>
          <span className="position-column-header">
            <span draggable onDragStart={event => startDrag(event, column.id)} onDragEnd={endDrag} className="positions-drag-handle" title={`Drag ${column.label} to reorder; keyboard controls are in Customize columns`}><DragIndicatorIcon fontSize="small" /></span>
            <button type="button" onClick={() => toggleSort(column.id)}>{column.label}{sort.id === column.id ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}</button>
          </span>
        </th>)}</tr></thead>
        <tbody>{filteredPositions.map((position) => {
          const key = `${position.source || mode}:${position.account_id}:${position.id || position.symbol}:${positionSide(position)}`;
          const isExpanded = expanded.has(key);
          return <React.Fragment key={key}><tr onClick={() => toggleExpanded(key)} className="position-data-row">
            {visibleColumns.map(column => {
              const value = valueForColumn(position, column.id);
              const isPnl = column.type === 'pnl' || column.type === 'pnl_percent';
              const pnlClass = isPnl && value > 0 ? 'position-gain' : isPnl && value < 0 ? 'position-loss' : '';
              return <td key={column.id} className={`${column.id === 'symbol' ? 'position-symbol' : ''} ${pnlClass}`}>
                {column.id === 'symbol' ? <button type="button" className="position-expand" aria-expanded={isExpanded} onClick={event => { event.stopPropagation(); toggleExpanded(key); }} title={position.symbol}>
                  <span>{isExpanded ? '▾' : '▸'} {instrumentName(position)}</span>
                  {instrumentName(position) !== position.symbol && <small>{position.symbol}</small>}
                  {assetType(position) === 'Event Contracts' && <span className={`position-outcome outcome-${positionSide(position).toLowerCase()}`}>{positionSide(position)}</span>}
                </button> : column.type === 'pnl' ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${formatCurrency(Math.abs(value))}`)
                  : column.type === 'pnl_percent' ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${Math.abs(value).toFixed(2)}%`)
                    : formatCell(value, column.type)}
              </td>;
            })}
          </tr>{isExpanded && <tr className="position-detail-row"><td colSpan={visibleColumns.length}><PositionDetails position={position} onSelectHolding={mode === 'QUANT' ? undefined : onSelectHolding} onOpenEventPosition={mode === 'QUANT' ? undefined : onOpenEventPosition} /></td></tr>}</React.Fragment>;
        })}</tbody>
      </table>
    </div>}
    {filterOpen && <PositionsDialog title="Position filters" onClose={() => setFilterOpen(false)}>
      <div className="positions-filter-group positions-field-filters">
        <label>Account<select value={accountFilter} onChange={e => setAccountFilter(e.target.value)}><option value="All">All accounts</option>{accounts.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label>Instrument / name<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Symbol or contract question" /></label>
      </div>
      <div className="positions-filter-group"><h4>Days to expiration</h4><div className="positions-filter-options">{[['All', null], ['≤ 1D', 1], ['≤ 7D', 7], ['≤ 30D', 30]].map(([label, value]) => <button type="button" key={label} aria-pressed={dteFilter === value} className={dteFilter === value ? 'active' : ''} onClick={() => setDteFilter(value)}>{label}</button>)}</div></div>
      <div className="positions-panel-footer"><button type="button" onClick={resetFilters}>Reset filters</button><button type="button" className="primary" onClick={() => setFilterOpen(false)}>Done</button></div>
    </PositionsDialog>}
    {columnsOpen && <PositionsDialog title="Customize columns" onClose={() => { setColumnsOpen(false); endDrag(); }}>
      <p className="positions-layout-help">{assetFilter}: drag to reorder or use the arrow buttons. Saved for your user on this browser across Positions views.</p>
      <div className="positions-column-list">{columnState.order.map((id, index) => {
        const column = COLUMN_MAP.get(id);
        return <div key={id} className={`positions-column-option ${dropTarget === id ? 'positions-drop-target' : ''}`} {...dragProps(id)}>
          <span draggable onDragStart={event => startDrag(event, id)} onDragEnd={endDrag} className="positions-drag-handle"><DragIndicatorIcon /></span>
          <span>{column.label}</span>
          <button type="button" disabled={index === 0} aria-label={`Move ${column.label} left`} onClick={() => updateColumnState(moveColumnState(columnState, id, columnState.order[index - 1]))}>←</button>
          <button type="button" disabled={index === columnState.order.length - 1} aria-label={`Move ${column.label} right`} onClick={() => updateColumnState(moveColumnState(columnState, id, columnState.order[index + 1]))}>→</button>
          <input type="checkbox" checked={columnState.selected.includes(id)} disabled={column.locked} onChange={() => toggleColumn(id)} aria-label={`Show ${column.label}`} />
        </div>;
      })}</div>
      <div className="positions-panel-footer"><button type="button" onClick={() => updateColumnState(defaultColumnState(assetFilter, true))}>Reset to defaults</button><button type="button" className="primary" onClick={() => setColumnsOpen(false)}>Done</button></div>
    </PositionsDialog>}
  </section>;
}
