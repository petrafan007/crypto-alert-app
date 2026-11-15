import React, { useEffect, useRef, useState } from 'react';

export const sanitizeDecimalInput = raw => {
  let value = String(raw).replace(/[^0-9.]/g, '');
  const parts = value.split('.');
  if (parts.length > 2) value = `${parts[0]}.${parts.slice(1).join('')}`;
  const [whole, fraction] = value.split('.');
  return fraction && fraction.length > 2 ? `${whole}.${fraction.substring(0, 2)}` : value;
};
export const formatDecimalInput = value => {
  const number = parseFloat(value);
  return Number.isFinite(number) ? number.toFixed(2) : '';
};
export const sanitizeIntegerInput = raw => String(raw).replace(/[^0-9]/g, '');
export const formatIntegerInput = value => {
  const number = parseInt(value, 10);
  return Number.isFinite(number) ? String(number) : '';
};

// A text field with two distinct states: the last saved value, and what the
// user is typing. While the field has focus a background refresh never
// replaces the typing. Once it is left, the field follows the saved value
// again, so the box and the row's data cannot disagree. `onCommit` may return
// false (or a promise of false) to report that the save did not happen; the
// field then returns to the saved value.
export default function CommittedInput({ value, sanitize = raw => raw, format = raw => raw, onCommit, ...props }) {
  const committed = value === null || value === undefined ? '' : String(value);
  const [draft, setDraft] = useState(committed);
  const editing = useRef(false);
  const latest = useRef(committed);
  latest.current = committed;
  useEffect(() => {
    if (!editing.current) setDraft(committed);
  }, [committed]);
  const commit = () => {
    const next = format(sanitize(draft));
    setDraft(next);
    if (next === latest.current) return;
    Promise.resolve(onCommit(next)).then(saved => {
      if (saved === false && !editing.current) setDraft(latest.current);
    }, () => {
      if (!editing.current) setDraft(latest.current);
    });
  };
  return (
    <input
      {...props}
      type="text"
      value={draft}
      onFocus={() => { editing.current = true; }}
      onChange={event => setDraft(sanitize(event.target.value))}
      onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }}
      onBlur={() => { editing.current = false; commit(); }}
    />
  );
}
