import axios from 'axios';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import FilterListIcon from '@mui/icons-material/FilterList';
import ViewColumnOutlinedIcon from '@mui/icons-material/ViewColumnOutlined';
import CloseIcon from '@mui/icons-material/Close';
import {
  ASSET_VIEWS, COLUMN_MAP, assetType, valueForColumn, formatCell, formatCurrency,
  instrumentName, positionSide, defaultColumnState, cleanColumnState,
  moveColumnState, resizeColumnState, columnStorageKey, mergeEventMarket,
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

const cents = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  const amount = parsed * 100;
  return `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}¢`;
};

function EventSymbolPopover({ position, market, onBuy, onSell, onClose }) {
  const symbol = String(position?.underlying_symbol || position?.symbol || '').replace(/ (YES|NO)$/i, '').trim().toUpperCase();
  const yesBid = market?.yes_bid;
  const yesAsk = market?.yes_ask;
  const noBid = market?.no_bid;
  const noAsk = market?.no_ask;
  const question = market?.event_title || position?.event_title || symbol;
  return (
    <div className="event-symbol-popover" role="tooltip" onClick={e => e.stopPropagation()}>
      <div className="event-symbol-popover-header">
        <span className="event-symbol-popover-symbol">{symbol}</span>
        <button type="button" className="event-symbol-popover-close" onClick={onClose} aria-label="Close"><CloseIcon fontSize="small" /></button>
      </div>
      {question && question !== symbol && <p className="event-symbol-popover-question">{question}</p>}
      <table className="event-symbol-popover-table">
        <thead><tr><th></th><th>Ask</th><th>Bid</th></tr></thead>
        <tbody>
          <tr><td className="outcome-label yes">YES</td><td>{cents(yesAsk)}</td><td>{cents(yesBid)}</td></tr>
          <tr><td className="outcome-label no">NO</td><td>{cents(noAsk)}</td><td>{cents(noBid)}</td></tr>
        </tbody>
      </table>
      <div className="event-symbol-popover-actions">
        <button type="button" className="event-popover-btn buy" onClick={onBuy}>Buy</button>
        <button type="button" className="event-popover-btn sell" onClick={onSell}>Sell</button>
      </div>
      <p className="event-symbol-popover-hint">Click row or Buy/Sell to manage this position</p>
    </div>
  );
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
  const [hoveredSymbol, setHoveredSymbol] = useState(null);
  const [hoveredPosition, setHoveredPosition] = useState(null);
  const hoverTimerRef = useRef(null);

  // All event contract base symbols held (for ongoing market data polling)
  const allEventSymbols = useMemo(() =>
    [...new Set(positions.filter(p => assetType(p) === 'Event Contracts').map(p => String(p.symbol || '').replace(/ (YES|NO)$/i, '').trim()).filter(Boolean))].sort(),
    [positions]
  );

  // Symbols still missing metadata (event_title or cutoff_at) — need aggressive re-fetch
  const missingSymbols = useMemo(() =>
    [...new Set(positions.filter(p => assetType(p) === 'Event Contracts' && (!p.event_title || !p.settlement?.cutoff_at)).map(p => String(p.symbol || '').replace(/ (YES|NO)$/i, '').trim()).filter(Boolean))].sort(),
    [positions]
  );

  // Fetch market data for a single symbol (shared helper)
  const fetchMarket = async (symbol, signal) => {
    const { data } = await axios.get('/api/webull/events/markets', { params: { symbol }, withCredentials: true, signal });
    const market = data?.markets?.find(item => item.symbol === symbol);
    if (!market) throw new Error('Contract metadata unavailable');
    return market;
  };

  // Aggressive re-poll (every 4 s, up to 12 attempts) for positions still missing metadata
  const retryCountRef = useRef({});
  useEffect(() => {
    if (!userId || !missingSymbols.length) return;
    const controller = new AbortController();
    const MAX_RETRIES = 12;
    const INTERVAL_MS = 4000;
    const pending = [...missingSymbols];
    (async () => {
      for (const symbol of pending) {
        if (!retryCountRef.current[symbol]) retryCountRef.current[symbol] = 0;
      }
      const poll = async () => {
        for (const symbol of pending) {
          if (controller.signal.aborted) return;
          if ((retryCountRef.current[symbol] || 0) >= MAX_RETRIES) continue;
          // If we already have a good market entry, skip
          if (markets[symbol] && !markets[symbol].unavailable && markets[symbol].settlement?.cutoff_at) continue;
          try {
            const market = await fetchMarket(symbol, controller.signal);
            if (!controller.signal.aborted) {
              setMarkets(current => ({ ...current, [symbol]: market }));
              retryCountRef.current[symbol] = MAX_RETRIES; // stop retrying once found
            }
          } catch {
            if (!controller.signal.aborted) {
              retryCountRef.current[symbol] = (retryCountRef.current[symbol] || 0) + 1;
              if (retryCountRef.current[symbol] >= MAX_RETRIES) {
                setMarkets(current => ({ ...current, [symbol]: { unavailable: true } }));
              }
            }
          }
        }
      };
      await poll();
      const timer = setInterval(poll, INTERVAL_MS);
      await new Promise(resolve => controller.signal.addEventListener('abort', resolve));
      clearInterval(timer);
    })();
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, missingSymbols.join(',')]);

  // Background poll (every 15 s) for ALL event contract market data (keeps bid/ask live for hover)
  useEffect(() => {
    if (!userId || !allEventSymbols.length) return;
    const controller = new AbortController();
    const INTERVAL_MS = 15000;
    const poll = async () => {
      for (const symbol of allEventSymbols) {
        if (controller.signal.aborted) break;
        try {
          const market = await fetchMarket(symbol, controller.signal);
          if (!controller.signal.aborted) setMarkets(current => ({ ...current, [symbol]: market }));
        } catch { /* keep existing */ }
      }
    };
    poll();
    const timer = setInterval(poll, INTERVAL_MS);
    return () => { controller.abort(); clearInterval(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, allEventSymbols.join(',')]);

  const [sort, setSort] = useState({ id: 'symbol', direction: 'asc' });
  const [draggedColumn, setDraggedColumn] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [isResizing, setIsResizing] = useState(false);
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
  const columnWidth = id => Number(columnState.widths?.[id]) || (id === 'symbol' ? 150 : 138);
  const startResize = (event, id) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = columnWidth(id);
    const startingState = columnState;
    setIsResizing(true);
    document.body.classList.add('is-resizing-columns');
    const move = moveEvent => {
      moveEvent.preventDefault();
      updateColumnState(resizeColumnState(startingState, id, startWidth + moveEvent.clientX - startX));
    };
    const stop = () => {
      setIsResizing(false);
      document.body.classList.remove('is-resizing-columns');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop);
  };
  const resetFilters = () => { setAssetFilter('All assets'); setAccountFilter('All'); setSearch(''); setDteFilter(null); };
  const modeLabel = mode === 'QUANT' ? 'Quantitative Strategy — Paper Positions' : mode === 'TEST' ? 'Test Mode — Paper Positions' : 'Real Trading — Positions';

  const handleSymbolHoverEnter = (position) => {
    if (assetType(position) !== 'Event Contracts') return;
    clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredPosition(position);
      const sym = String(position.symbol || '').replace(/ (YES|NO)$/i, '').trim();
      setHoveredSymbol(sym);
    }, 200);
  };
  const handleSymbolHoverLeave = () => {
    clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredSymbol(null);
      setHoveredPosition(null);
    }, 300);
  };
  const closePopover = () => {
    clearTimeout(hoverTimerRef.current);
    setHoveredSymbol(null);
    setHoveredPosition(null);
  };

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
        <colgroup>{visibleColumns.map(column => <col key={column.id} style={{ width: `${columnWidth(column.id)}px` }} />)}</colgroup>
        <thead><tr>{visibleColumns.map(column => <th key={column.id} scope="col" aria-sort={sort.id === column.id ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} className={dropTarget === column.id ? 'positions-drop-target' : ''} draggable={!isResizing} onDragStart={event => startDrag(event, column.id)} onDragEnd={endDrag} title={`Drag ${column.label} to reorder`} style={{ width: `${columnWidth(column.id)}px`, minWidth: `${columnWidth(column.id)}px`, maxWidth: `${columnWidth(column.id)}px` }} {...dragProps(column.id)}>
          <span className="position-column-header">
            <button type="button" onClick={() => toggleSort(column.id)}>{column.label}{sort.id === column.id ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}</button>
          </span>
          <span className="positions-column-resizer" draggable={false} onDragStart={event => { event.preventDefault(); event.stopPropagation(); }} onMouseDown={event => startResize(event, column.id)} title={`Resize ${column.label}`} />
        </th>)}</tr></thead>
        <tbody>{filteredPositions.map((position) => {
          const key = `${position.source || mode}:${position.account_id}:${position.id || position.symbol}:${positionSide(position)}`;
          const isEventContract = assetType(position) === 'Event Contracts';
          const baseSymbol = String(position.symbol || '').replace(/ (YES|NO)$/i, '').trim();
          const posMarket = markets[baseSymbol];
          const isPopoverOpen = isEventContract && hoveredSymbol === baseSymbol && hoveredPosition === position;
          return <tr
            key={key}
            className={`position-data-row${isEventContract ? ' event-contract-row' : ''}`}
            onClick={isEventContract ? () => { closePopover(); onOpenEventPosition?.(position); } : undefined}
            title={isEventContract ? 'Click to manage this event contract position' : undefined}
          >
            {visibleColumns.map(column => {
              const value = valueForColumn(position, column.id);
              const isPnl = column.type === 'pnl' || column.type === 'pnl_percent';
              const pnlClass = isPnl && value > 0 ? 'position-gain' : isPnl && value < 0 ? 'position-loss' : '';
              if (column.id === 'symbol' && isEventContract) {
                return <td key={column.id} className={`position-symbol ${pnlClass}`} style={{ position: 'relative' }}
                  onMouseEnter={() => handleSymbolHoverEnter(position)}
                  onMouseLeave={handleSymbolHoverLeave}
                  onClick={e => e.stopPropagation()}
                >
                  {String(position.symbol || '—').toUpperCase()}
                  {isPopoverOpen && (
                    <EventSymbolPopover
                      position={position}
                      market={posMarket}
                      onClose={closePopover}
                      onBuy={() => { closePopover(); onOpenEventPosition?.(position); }}
                      onSell={() => { closePopover(); onOpenEventPosition?.(position); }}
                    />
                  )}
                </td>;
              }
              return <td title={column.id === 'mark' ? position.quote_status : undefined} key={column.id} className={`${column.id === 'symbol' ? 'position-symbol' : ''} ${pnlClass}`}>
                {column.id === 'symbol' ? String(position.symbol || '—').toUpperCase() : column.type === 'pnl' ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${formatCurrency(Math.abs(value))}`)
                  : column.type === 'pnl_percent' ? (value === null ? '—' : `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${Math.abs(value).toFixed(2)}%`)
                    : formatCell(value, column.type)}
              </td>;
            })}
          </tr>;
        })}</tbody>
      </table>
    </div>}
    {filterOpen && <PositionsDialog title="Position filters" onClose={() => setFilterOpen(false)}>
      <div className="positions-filter-group positions-field-filters">
        <label>Account<select value={accountFilter} onChange={e => setAccountFilter(e.target.value)}><option value="All">All accounts</option>{accounts.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label>Symbol / ticker<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Symbol or contract question" /></label>
      </div>
      <div className="positions-filter-group"><h4>Days to expiration</h4><div className="positions-filter-options">{[['All', null], ['≤ 1D', 1], ['≤ 7D', 7], ['≤ 30D', 30]].map(([label, value]) => <button type="button" key={label} aria-pressed={dteFilter === value} className={dteFilter === value ? 'active' : ''} onClick={() => setDteFilter(value)}>{label}</button>)}</div></div>
      <div className="positions-panel-footer"><button type="button" onClick={resetFilters}>Reset filters</button><button type="button" className="primary" onClick={() => setFilterOpen(false)}>Done</button></div>
    </PositionsDialog>}
    {columnsOpen && <PositionsDialog title="Customize columns" onClose={() => { setColumnsOpen(false); endDrag(); }}>
      <p className="positions-layout-help">{assetFilter}: drag to reorder or use the arrow buttons. Saved for your user on this browser across Positions views.</p>
      <div className="positions-column-list">{columnState.order.map((id, index) => {
        const column = COLUMN_MAP.get(id);
        return <div key={id} draggable onDragStart={event => startDrag(event, id)} onDragEnd={endDrag} className={`positions-column-option ${dropTarget === id ? 'positions-drop-target' : ''}`} {...dragProps(id)}>
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
