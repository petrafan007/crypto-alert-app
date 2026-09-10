import React, { useEffect, useMemo, useRef, useState } from 'react';
import CloseIcon from '@mui/icons-material/Close';
import FilterListIcon from '@mui/icons-material/FilterList';
import ViewColumnOutlinedIcon from '@mui/icons-material/ViewColumnOutlined';
import {
  cleanOrderTableState,
  defaultOrderTableState,
  moveOrderTableColumn,
  resizeOrderTableColumn,
} from '../utils/orderTable.mjs';
import './WebullPositions.css';
import './ConfigurableOrderTable.css';

function OrderTableDialog({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="positions-dialog" aria-label={title} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="positions-panel-title"><h3>{title}</h3><button type="button" onClick={onClose} aria-label={`Close ${title}`}><CloseIcon /></button></div>
    {children}
  </dialog>;
}

function storageKey(userId, tableId) {
  if (!tableId) return null;
  return `order-table-state-v1:${encodeURIComponent(userId ?? 'local')}:${encodeURIComponent(tableId)}`;
}

function normalizedValue(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function compareValues(left, right) {
  if ((left === null || left === undefined || left === '') && (right === null || right === undefined || right === '')) return 0;
  if (left === null || left === undefined || left === '') return 1;
  if (right === null || right === undefined || right === '') return -1;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  const leftDate = Date.parse(left);
  const rightDate = Date.parse(right);
  if (Number.isFinite(leftDate) && Number.isFinite(rightDate) && /[-/:T]/.test(String(left))) return leftDate - rightDate;
  return normalizedValue(left).localeCompare(normalizedValue(right), undefined, { numeric: true, sensitivity: 'base' });
}

export default function ConfigurableOrderTable({
  rows = [], columns = [], tableId, userId, emptyText = 'No orders available.',
  rowKey = (row, index) => row.id ?? index, defaultSort = { id: 'created_at', direction: 'desc' },
  tableClassName = '', rowClassName,
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [draggedColumn, setDraggedColumn] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [isResizing, setIsResizing] = useState(false);
  const key = storageKey(userId, tableId);
  const columnSignature = columns.map((column) => `${column.id}:${column.defaultVisible !== false}:${Boolean(column.locked)}`).join('|');
  const [state, setState] = useState(() => {
    try { return cleanOrderTableState(key ? JSON.parse(localStorage.getItem(key)) : null, columns, defaultSort); }
    catch { return defaultOrderTableState(columns, defaultSort); }
  });

  useEffect(() => {
    setState((current) => cleanOrderTableState(current, columns, defaultSort));
  }, [columnSignature, defaultSort?.id, defaultSort?.direction]);

  useEffect(() => {
    if (!key) return;
    try {
      const saved = localStorage.getItem(key);
      setState(cleanOrderTableState(saved ? JSON.parse(saved) : null, columns, defaultSort));
    } catch { setState(defaultOrderTableState(columns, defaultSort)); }
  }, [key, columnSignature, defaultSort?.id, defaultSort?.direction]);

  useEffect(() => {
    const sync = (event) => {
      if (event.key !== key) return;
      try { setState(cleanOrderTableState(event.newValue ? JSON.parse(event.newValue) : null, columns, defaultSort)); }
      catch { setState(defaultOrderTableState(columns, defaultSort)); }
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [key, columnSignature, defaultSort?.id, defaultSort?.direction]);

  const updateState = (nextOrUpdater) => {
    setState((current) => {
      const next = typeof nextOrUpdater === 'function' ? nextOrUpdater(current) : nextOrUpdater;
      try { if (key) localStorage.setItem(key, JSON.stringify(next)); } catch { /* Keep the in-session layout when storage is unavailable. */ }
      return next;
    });
  };

  const columnMap = useMemo(() => new Map(columns.map((column) => [column.id, column])), [columns]);
  const visibleColumns = state.order.filter((id) => state.selected.includes(id)).map((id) => columnMap.get(id)).filter(Boolean);
  const filterableColumns = columns.filter((column) => column.filterable);
  const filterOptions = useMemo(() => Object.fromEntries(filterableColumns.map((column) => [
    column.id,
    [...new Set(rows.map((row) => normalizedValue(column.value(row))).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
  ])), [rows, filterableColumns]);
  const displayedRows = useMemo(() => {
    const search = state.filters.search.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (search && !columns.some((column) => normalizedValue(column.searchValue ? column.searchValue(row) : column.value(row)).toLowerCase().includes(search))) return false;
      return Object.entries(state.filters.values).every(([id, expected]) => {
        if (!expected) return true;
        const column = columnMap.get(id);
        return column && normalizedValue(column.value(row)) === expected;
      });
    });
    if (!state.sort) return filtered;
    const sortColumn = columnMap.get(state.sort.id);
    if (!sortColumn) return filtered;
    return [...filtered].sort((left, right) => {
      const comparison = compareValues(sortColumn.sortValue ? sortColumn.sortValue(left) : sortColumn.value(left), sortColumn.sortValue ? sortColumn.sortValue(right) : sortColumn.value(right));
      return state.sort.direction === 'asc' ? comparison : -comparison;
    });
  }, [rows, columns, columnMap, state.filters, state.sort]);

  const activeFilterCount = (state.filters.search ? 1 : 0) + Object.values(state.filters.values).filter(Boolean).length;
  const toggleSort = (id) => updateState((current) => ({ ...current, sort: { id, direction: current.sort?.id === id && current.sort.direction === 'asc' ? 'desc' : 'asc' } }));
  const toggleColumn = (id) => updateState((current) => {
    if (columnMap.get(id)?.locked) return current;
    return { ...current, selected: current.selected.includes(id) ? current.selected.filter((keyId) => keyId !== id) : [...current.selected, id] };
  });
  const endDrag = () => { setDraggedColumn(null); setDropTarget(null); };
  const dragProps = (id) => ({
    onDragOver: (event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; setDropTarget(id); },
    onDrop: (event) => {
      event.preventDefault();
      const source = event.dataTransfer.getData('text/plain') || draggedColumn;
      updateState((current) => moveOrderTableColumn(current, source, id));
      endDrag();
    },
  });
  const startDrag = (event, id) => { setDraggedColumn(id); event.dataTransfer.setData('text/plain', id); event.dataTransfer.effectAllowed = 'move'; };
  const columnWidth = (column) => Number(state.widths?.[column.id]) || Number(column.defaultWidth) || (column.id === 'symbol' ? 160 : 140);
  const tableWidth = visibleColumns.reduce((total, column) => total + columnWidth(column), 0);
  const startResize = (event, column) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = columnWidth(column);
    const startingState = state;
    setIsResizing(true);
    document.body.classList.add('is-resizing-columns');
    const move = (moveEvent) => {
      moveEvent.preventDefault();
      updateState(resizeOrderTableColumn(startingState, column.id, startWidth + moveEvent.clientX - startX));
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
  const resetFilters = () => updateState((current) => ({ ...current, filters: { search: '', values: {} } }));

  const isColumnPinned = (col) => Boolean(col?.locked || (col?.id === 'symbol' && columns[0]?.id === 'symbol'));

  return <div className="configurable-order-table webull-positions">
    <div className="configurable-order-actions">
      <span>{displayedRows.length} of {rows.length} orders{activeFilterCount ? ` · ${activeFilterCount} active filter${activeFilterCount === 1 ? '' : 's'}` : ''}</span>
      <div className="webull-positions-actions">
        <button type="button" onClick={() => setFilterOpen(true)}><FilterListIcon fontSize="small" /> Filter</button>
        <button type="button" onClick={() => setColumnsOpen(true)}><ViewColumnOutlinedIcon fontSize="small" /> Customize columns</button>
      </div>
    </div>
    {!displayedRows.length ? (
      <div className="empty-state">
        <p>{rows.length ? 'No orders match the saved filters.' : emptyText}</p>
        {rows.length > 0 && <button type="button" className="btn btn-secondary" onClick={resetFilters}>Reset filters</button>}
      </div>
    ) : (
      <div className={`webull-positions-table-wrap order-table-scroll ${tableClassName}`}>
        <table className="webull-positions-table" style={{ '--order-table-width': `${tableWidth}px` }}>
          <colgroup>
            {visibleColumns.map((column) => <col key={column.id} style={{ width: `${columnWidth(column)}px` }} />)}
          </colgroup>
          <thead>
            <tr>
              {visibleColumns.map((column) => {
                const pinned = isColumnPinned(column);
                return (
                  <th
                    key={column.id}
                    scope="col"
                    aria-sort={state.sort?.id === column.id ? (state.sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                    className={dropTarget === column.id ? 'positions-drop-target' : ''}
                    draggable={!isResizing && !pinned}
                    onDragStart={(event) => startDrag(event, column.id)}
                    onDragEnd={endDrag}
                    title={pinned ? `${column.label} is pinned` : `Drag ${column.label} to reorder`}
                    style={{
                      width: `${columnWidth(column)}px`,
                      minWidth: `${columnWidth(column)}px`,
                      maxWidth: `${columnWidth(column)}px`,
                      ...column.headerStyle,
                    }}
                    {...dragProps(column.id)}
                  >
                    <span className="position-column-header">
                      <button type="button" className="order-header-btn" onClick={() => toggleSort(column.id)}>
                        {column.label}
                        {state.sort?.id === column.id ? (state.sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}
                      </button>
                    </span>
                    <span
                      className="positions-column-resizer order-column-resizer"
                      draggable={false}
                      onDragStart={(event) => { event.preventDefault(); event.stopPropagation(); }}
                      onMouseDown={(event) => startResize(event, column)}
                      title={`Resize ${column.label}`}
                    />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((row, index) => (
              <tr key={rowKey(row, index)} className={`position-data-row ${typeof rowClassName === 'function' ? rowClassName(row, index) : (rowClassName || '')}`}>
                {visibleColumns.map((column) => (
                  <td
                    key={column.id}
                    className={`${column.id === 'symbol' ? 'position-symbol' : ''} ${typeof column.className === 'function' ? column.className(row) : (column.className || '')}`}
                    style={typeof column.style === 'function' ? column.style(row) : column.style}
                  >
                    {column.render ? column.render(row) : normalizedValue(column.value(row)) || '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
    {filterOpen && <OrderTableDialog title="Order filters" onClose={() => setFilterOpen(false)}>
      <div className="positions-filter-group positions-field-filters">
        <label>Search all columns<input type="search" value={state.filters.search} onChange={(event) => updateState((current) => ({ ...current, filters: { ...current.filters, search: event.target.value } }))} placeholder="Symbol, status, account…" /></label>
        {filterableColumns.map((column) => <label key={column.id}>{column.label}<select value={state.filters.values[column.id] || ''} onChange={(event) => updateState((current) => ({ ...current, filters: { ...current.filters, values: { ...current.filters.values, [column.id]: event.target.value } } }))}><option value="">All</option>{filterOptions[column.id].map((option) => <option key={option} value={option}>{column.filterLabel ? column.filterLabel(option) : option}</option>)}</select></label>)}
      </div>
      <div className="positions-panel-footer"><button type="button" onClick={resetFilters}>Reset filters</button><button type="button" className="primary" onClick={() => setFilterOpen(false)}>Done</button></div>
    </OrderTableDialog>}
    {columnsOpen && <OrderTableDialog title="Customize columns" onClose={() => { setColumnsOpen(false); endDrag(); }}>
      <p className="positions-layout-help">Drag any unpinned column to reorder or use the arrow buttons. Pinned columns stay locked first. Columns, widths, filters, and sorting are saved for your user on this browser.</p>
      <div className="positions-column-list">{state.order.map((id, index) => { const column = columnMap.get(id); if (!column) return null; const pinned = isColumnPinned(column); return <div key={id} draggable={!pinned} onDragStart={(event) => startDrag(event, id)} onDragEnd={endDrag} className={`positions-column-option ${pinned ? 'order-column-pinned' : ''} ${dropTarget === id ? 'positions-drop-target' : ''}`} {...dragProps(id)}><span>{column.label}</span><button type="button" disabled={pinned || index === 0} aria-label={`Move ${column.label} left`} onClick={() => updateState((current) => moveOrderTableColumn(current, id, current.order[index - 1]))}>←</button><button type="button" disabled={pinned || index === state.order.length - 1} aria-label={`Move ${column.label} right`} onClick={() => updateState((current) => moveOrderTableColumn(current, id, current.order[index + 1]))}>→</button><input type="checkbox" checked={state.selected.includes(id)} disabled={pinned || column.locked} onChange={() => toggleColumn(id)} aria-label={`Show ${column.label}`} /></div>; })}</div>
      <div className="positions-panel-footer"><button type="button" onClick={() => updateState(defaultOrderTableState(columns, defaultSort))}>Reset to defaults</button><button type="button" className="primary" onClick={() => setColumnsOpen(false)}>Done</button></div>
    </OrderTableDialog>}
  </div>;
}
