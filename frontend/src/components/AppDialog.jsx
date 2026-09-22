import React, { useEffect, useState } from 'react';
import './AppDialog.css';

let listener = null;
const queue = [];

function dispatchNext() {
  if (listener && queue.length) listener(queue[0]);
}

export function showAppDialog(options) {
  return new Promise(resolve => {
    queue.push({ options, resolve });
    dispatchNext();
  });
}

export const showAppAlert = (message, options = {}) => showAppDialog({ ...options, message, cancelLabel: null });
export const showAppConfirm = (message, options = {}) => showAppDialog({ ...options, message, cancelLabel: options.cancelLabel || 'Keep Current' });

export default function AppDialogHost() {
  const [entry, setEntry] = useState(null);
  useEffect(() => {
    listener = setEntry;
    dispatchNext();
    return () => { listener = null; };
  }, []);
  if (!entry) return null;
  const { options, resolve } = entry;
  const finish = result => {
    queue.shift();
    setEntry(null);
    resolve(result);
    window.setTimeout(dispatchNext, 0);
  };
  return <div className="app-dialog-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && options.cancelLabel) finish(false); }}>
    <section className={`app-dialog app-dialog-${options.tone || 'info'}`} role="alertdialog" aria-modal="true" aria-labelledby="app-dialog-title" aria-describedby="app-dialog-message">
      <header><span aria-hidden="true">{options.icon || (options.tone === 'danger' ? '⚠️' : 'ℹ️')}</span><h2 id="app-dialog-title">{options.title || 'Crypto & Securities Dashboard'}</h2></header>
      <p id="app-dialog-message">{options.message}</p>
      <footer>
        {options.cancelLabel && <button type="button" className="app-dialog-secondary" onClick={() => finish(false)}>{options.cancelLabel}</button>}
        <button type="button" autoFocus className={options.tone === 'danger' ? 'app-dialog-danger' : 'app-dialog-primary'} onClick={() => finish(true)}>{options.confirmLabel || 'OK'}</button>
      </footer>
    </section>
  </div>;
}
