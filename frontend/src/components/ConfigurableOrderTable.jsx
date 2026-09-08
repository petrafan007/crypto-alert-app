import React, { useEffect, useMemo, useRef, useState } from 'react';
import CloseIcon from '@mui/icons-material/Close';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import FilterListIcon from '@mui/icons-material/FilterList';
import ViewColumnOutlinedIcon from '@mui/icons-material/ViewColumnOutlined';
import './WebullPositions.css';
import './ConfigurableOrderTable.css';

const EMPTY_FILTERS = Object.freeze({ search: '', values: {} });

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

function defaultState(columns, defaultSort) {
  return {
    order: columns.map((column) => column.id),
    selected: columns.filter((column) => column.defaultVisible !== false).map((column) => column.id),
    sort: defaultSort || null,
    filters: { ...EMPTY_FILTERS, values: {} },
  };
}

function cleanState(saved, columns, defaultSort) {
  const defaults = defaultState(columns, defaultSort);
  if (!saved || !Array.isArray(saved.order) || !Array.isArray(saved.selected)) return defaults;
  const validIds = new Set(columns.map((column) => column.id));
  const lockedIds = columns.filter((column) => column.locked).map((column) => column.id);
  const order = [...new Set(saved.order.filter((id) => validIds.has(id)))];
  const selected = [...new Set([...lockedIds, ...saved.selected.filter((id) => validIds.has(id))])];
  const sort = saved.sort && validIds.has(saved.sort.id) && ['asc', 'desc'].includes(saved.sort.direction)
    ? saved.sort
    : defaults.sort;
  const values = saved.filters?.values && typeof saved.filters.values === 'object'
    ? Object.fromEntries(Object.entries(saved.filters.values).filter(([id]) => validIds.has(id)))
    : {};
  return {
    order: [...order, ...defaults.order.filter((id) => !order.includes(id))],
    selected,
    sort,
    filters: { search: typeof saved.filters?.search === 'string' ? saved.filters.search : '', values },
  };
}

function moveColumn(state, source, target) {
  if (!source || source === target || !state.order.includes(source) || !state.order.includes(target)) return state;
  const order = [...state.order];
  const targetIndex = order.indexOf(target);
  order.splice(order.indexOf(source), 1);
  order.splice(targetIndex, 0, source);
  return { ...state, order };
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
  const key = storageKey(userId, tableId);
  const columnSignature = columns.map((column) => `${column.id}:${column.defaultVisible !== false}:${Boolean(column.locked)}`).join('|');
  const [state, setState] = useState(() => {
    try { return cleanState(key ? JSON.parse(localStorage.getItem(key)) : null, columns, defaultSort); }
    catch { return defaultState(columns, defaultSort); }
  });

  useEffect(() => {
    setState((current) => cleanState(current, columns, defaultSort));
  }, [columnSignature, defaultSort?.id, defaultSort?.direction]);

  useEffect(() => {
    if (!key) return;
    try {
      const saved = localStorage.getItem(key);
      setState(cleanState(saved ? JSON.parse(saved) : null, columns, defaultSort));
    } catch { setState(defaultState(columns, defaultSort)); }
  }, [key, columnSignature, defaultSort?.id, defaultSort?.direction]);

  useEffect(() => {
    const sync = (event) => {
      if (event.key !== key) return;
      try { setState(cleanState(event.newValue ? JSON.parse(event.newValue) : null, columns, defaultSort)); }
      catch { setState(defaultState(columns, defaultSort)); }
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
    onDragOver: (event) => { if (draggedColumn) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; setDropTarget(id); } },
    onDrop: (event) => { event.preventDefault(); updateState((current) => moveColumn(current, draggedColumn, id)); endDrag(); },
  });
  const startDrag = (event, id) => { setDraggedColumn(id); event.dataTransfer.setData('text/plain', id); event.dataTransfer.effectAllowed = 'move'; };
  const resetFilters = () => updateState((current) => ({ ...current, filters: { search: '', values: {} } }));

  return <div className="configurable-order-table webull-positions">
    <div className="configurable-order-actions">
      <span>{displayedRows.length} of {rows.length} orders{activeFilterCount ? ` · ${activeFilterCount} active filter${activeFilterCount === 1 ? '' : 's'}` : ''}</span>
      <div className="webull-positions-actions">
        <button type="button" onClick={() => setFilterOpen(true)}><FilterListIcon fontSize="small" /> Filter</button>
        <button type="button" onClick={() => setColumnsOpen(true)}><ViewColumnOutlinedIcon fontSize="small" /> Customize columns</button>
      </div>
    </div>
    {!displayedRows.length ? <div className="empty-state"><p>{rows.length ? 'No orders match the saved filters.' : emptyText}</p>{rows.length > 0 && <button type="button" className="btn btn-secondary" onClick={resetFilters}>Reset filters</button>}</div> : <div className={`table-container trading-table ${tableClassName}`}>
      <div className="order-table-scroll"><table><thead><tr>{visibleColumns.map((column) => <th key={column.id} scope="col" aria-sort={state.sort?.id === column.id ? (state.sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} className={dropTarget === column.id ? 'positions-drop-target' : ''} style={column.headerStyle} {...dragProps(column.id)}>
        <span className="position-column-header"><span draggable onDragStart={(event) => startDrag(event, column.id)} onDragEnd={endDrag} className="positions-drag-handle" title={`Drag ${column.label} to reorder; keyboard controls are in Customize columns`}><DragIndicatorIcon fontSize="small" /></span><button type="button" onClick={() => toggleSort(column.id)}>{column.label}{state.sort?.id === column.id ? (state.sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}</button></span>
      </th>)}</tr></thead><tbody>{displayedRows.map((row, index) => <tr key={rowKey(row, index)} className={typeof rowClassName === 'function' ? rowClassName(row, index) : rowClassName}>{visibleColumns.map((column) => <td key={column.id} className={typeof column.className === 'function' ? column.className(row) : column.className} style={typeof column.style === 'function' ? column.style(row) : column.style}>{column.render ? column.render(row) : normalizedValue(column.value(row)) || '—'}</td>)}</tr>)}</tbody></table></div>
    </div>}
    {filterOpen && <OrderTableDialog title="Order filters" onClose={() => setFilterOpen(false)}>
      <div className="positions-filter-group positions-field-filters">
        <label>Search all columns<input type="search" value={state.filters.search} onChange={(event) => updateState((current) => ({ ...current, filters: { ...current.filters, search: event.target.value } }))} placeholder="Symbol, status, account…" /></label>
        {filterableColumns.map((column) => <label key={column.id}>{column.label}<select value={state.filters.values[column.id] || ''} onChange={(event) => updateState((current) => ({ ...current, filters: { ...current.filters, values: { ...current.filters.values, [column.id]: event.target.value } } }))}><option value="">All</option>{filterOptions[column.id].map((option) => <option key={option} value={option}>{column.filterLabel ? column.filterLabel(option) : option}</option>)}</select></label>)}
      </div>
      <div className="positions-panel-footer"><button type="button" onClick={resetFilters}>Reset filters</button><button type="button" className="primary" onClick={() => setFilterOpen(false)}>Done</button></div>
    </OrderTableDialog>}
    {columnsOpen && <OrderTableDialog title="Customize columns" onClose={() => { setColumnsOpen(false); endDrag(); }}>
      <p className="positions-layout-help">Drag to reorder or use the arrow buttons. Columns, filters, and sorting are saved for your user on this browser.</p>
      <div className="positions-column-list">{state.order.map((id, index) => { const column = columnMap.get(id); if (!column) return null; return <div key={id} className={`positions-column-option ${dropTarget === id ? 'positions-drop-target' : ''}`} {...dragProps(id)}><span draggable onDragStart={(event) => startDrag(event, id)} onDragEnd={endDrag} className="positions-drag-handle"><DragIndicatorIcon /></span><span>{column.label}</span><button type="button" disabled={index === 0} aria-label={`Move ${column.label} left`} onClick={() => updateState((current) => moveColumn(current, id, current.order[index - 1]))}>←</button><button type="button" disabled={index === state.order.length - 1} aria-label={`Move ${column.label} right`} onClick={() => updateState((current) => moveColumn(current, id, current.order[index + 1]))}>→</button><input type="checkbox" checked={state.selected.includes(id)} disabled={column.locked} onChange={() => toggleColumn(id)} aria-label={`Show ${column.label}`} /></div>; })}</div>
      <div className="positions-panel-footer"><button type="button" onClick={() => updateState(defaultState(columns, defaultSort))}>Reset to defaults</button><button type="button" className="primary" onClick={() => setColumnsOpen(false)}>Done</button></div>
    </OrderTableDialog>}
  </div>;
}
