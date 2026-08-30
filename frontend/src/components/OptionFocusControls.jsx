import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  DEFAULT_FOCUS_COLUMNS,
  FOCUS_OPTIONS,
  OPTION_COLUMN_GROUPS,
  OPTION_COLUMNS,
} from '../utils/optionChainColumns';

function OptionItemsModal({ focus, selected, onDone, onClose }) {
  const [draft, setDraft] = useState([...selected]);
  const [expanded, setExpanded] = useState({ quote: true, greeks: true, analysis: true });
  const modalRef = useRef(null);

  useEffect(() => {
    const previous = document.activeElement;
    modalRef.current?.focus();
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previous?.focus?.();
    };
  }, [onClose]);

  const toggle = (id) => setDraft((current) => current.includes(id)
    ? current.filter((item) => item !== id)
    : [...current, id]);
  const toggleGroup = (items) => setDraft((current) => {
    const ids = items.map((item) => item.id);
    return ids.every((id) => current.includes(id))
      ? current.filter((id) => !ids.includes(id))
      : [...current, ...ids.filter((id) => !current.includes(id))];
  });

  return createPortal(
    <div className="option-items-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="option-items-modal" role="dialog" aria-modal="true" aria-labelledby="option-items-title" ref={modalRef} tabIndex="-1">
        <header>
          <h2 id="option-items-title">Option Items</h2>
          <button type="button" className="option-items-close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="option-items-headings"><span>Available Items</span><span>Selected Items</span></div>
        <div className="option-items-body">
          <div className="option-items-available">
            {OPTION_COLUMN_GROUPS.map((group) => {
              const allSelected = group.items.every((item) => draft.includes(item.id));
              return (
                <section key={group.id}>
                  <div className="option-group-heading">
                    <label><input type="checkbox" checked={allSelected} onChange={() => toggleGroup(group.items)} /> {group.label}</label>
                    <button type="button" onClick={() => setExpanded((value) => ({ ...value, [group.id]: !value[group.id] }))} aria-label={`${expanded[group.id] ? 'Collapse' : 'Expand'} ${group.label}`}>{expanded[group.id] ? '⌃' : '⌄'}</button>
                  </div>
                  {expanded[group.id] && group.items.map((item) => (
                    <label className="option-item-check" key={item.id}>
                      <input type="checkbox" checked={draft.includes(item.id)} onChange={() => toggle(item.id)} />
                      <span>{item.label}</span>
                    </label>
                  ))}
                </section>
              );
            })}
          </div>
          <div className="option-items-selected">
            {draft.length ? draft.map((id) => (
              <label className="option-item-check" key={id}>
                <input type="checkbox" checked onChange={() => toggle(id)} />
                <span>{OPTION_COLUMNS[id]?.label || id}</span>
              </label>
            )) : <p className="option-items-empty">Choose at least one item.</p>}
          </div>
        </div>
        <footer>
          <button type="button" className="option-reset-button" onClick={() => setDraft([...DEFAULT_FOCUS_COLUMNS[focus.id]])}>Reset to Defaults</button>
          <button type="button" className="option-done-button" disabled={!draft.length} onClick={() => onDone(draft)}>Done</button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

export default function OptionFocusControls({ activeFocus, profiles, onFocusChange, onProfileChange }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const rootRef = useRef(null);
  const active = FOCUS_OPTIONS.find((focus) => focus.id === activeFocus) || FOCUS_OPTIONS[0];

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => { if (!rootRef.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <>
      <div className="option-focus-control" ref={rootRef}>
        <span className="chain-control-label">Focus:</span>
        <button type="button" className="option-focus-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          <span>{active.label}</span><span aria-hidden="true">⌄</span>
        </button>
        {open && (
          <div className="option-focus-menu">
            {FOCUS_OPTIONS.map((focus) => (
              <div className={`option-focus-row ${focus.id === activeFocus ? 'active' : ''}`} key={focus.id}>
                <button type="button" className="option-focus-choice" onClick={() => { onFocusChange(focus.id); setOpen(false); }}>{focus.label}</button>
                <button type="button" className="option-focus-edit" onClick={() => { setEditing(focus); setOpen(false); }} aria-label={`Edit ${focus.label}`} title={`Edit ${focus.label}`}>✎</button>
              </div>
            ))}
          </div>
        )}
      </div>
      {editing && (
        <OptionItemsModal
          focus={editing}
          selected={profiles[editing.id]}
          onClose={() => setEditing(null)}
          onDone={(items) => { onProfileChange(editing.id, items); setEditing(null); }}
        />
      )}
    </>
  );
}
