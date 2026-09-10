const MIN_COLUMN_WIDTH = 80;
const MAX_COLUMN_WIDTH = 800;

export function orderTableColumnIds(columns) {
  const ids = columns.map((column) => column.id);
  return ids.includes('symbol') ? ['symbol', ...ids.filter((id) => id !== 'symbol')] : ids;
}

export function defaultOrderTableState(columns, defaultSort) {
  const order = orderTableColumnIds(columns);
  return {
    order,
    selected: order.filter((id) => id === 'symbol' || columns.find((column) => column.id === id)?.defaultVisible !== false),
    sort: defaultSort || null,
    filters: { search: '', values: {} },
    widths: {},
  };
}

export function cleanOrderTableState(saved, columns, defaultSort) {
  const defaults = defaultOrderTableState(columns, defaultSort);
  if (!saved || !Array.isArray(saved.order) || !Array.isArray(saved.selected)) return defaults;
  const validIds = new Set(columns.map((column) => column.id));
  const symbolFirst = (ids) => validIds.has('symbol')
    ? ['symbol', ...ids.filter((id) => id !== 'symbol')]
    : ids;
  const lockedIds = columns.filter((column) => column.locked).map((column) => column.id);
  if (validIds.has('symbol')) lockedIds.unshift('symbol');
  const savedOrder = [...new Set(saved.order.filter((id) => validIds.has(id)))];
  const order = symbolFirst([...savedOrder, ...defaults.order.filter((id) => !savedOrder.includes(id))]);
  const selected = [...new Set([...lockedIds, ...saved.selected.filter((id) => validIds.has(id))])];
  const sort = saved.sort && validIds.has(saved.sort.id) && ['asc', 'desc'].includes(saved.sort.direction)
    ? saved.sort
    : defaults.sort;
  const values = saved.filters?.values && typeof saved.filters.values === 'object'
    ? Object.fromEntries(Object.entries(saved.filters.values).filter(([id]) => validIds.has(id)))
    : {};
  const widths = Object.fromEntries(Object.entries(saved.widths || {}).flatMap(([id, width]) => {
    const numericWidth = Number(width);
    return validIds.has(id) && Number.isFinite(numericWidth)
      ? [[id, Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, Math.round(numericWidth)))]]
      : [];
  }));
  return {
    order,
    selected,
    sort,
    filters: { search: typeof saved.filters?.search === 'string' ? saved.filters.search : '', values },
    widths,
  };
}

export function moveOrderTableColumn(state, source, target) {
  if (!source || source === 'symbol' || source === target || !state.order.includes(source) || !state.order.includes(target)) return state;
  const order = [...state.order];
  const targetIndex = order.indexOf(target);
  order.splice(order.indexOf(source), 1);
  order.splice(targetIndex, 0, source);
  if (order.includes('symbol')) {
    order.splice(order.indexOf('symbol'), 1);
    order.unshift('symbol');
  }
  return { ...state, order };
}

export function resizeOrderTableColumn(state, id, width) {
  if (!state.order.includes(id) || !Number.isFinite(Number(width))) return state;
  return {
    ...state,
    widths: {
      ...(state.widths || {}),
      [id]: Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, Math.round(Number(width)))),
    },
  };
}
