import React, { useEffect, useMemo, useState } from 'react';
import { formatEasternDateTime } from '../utils/dateTime';

const PAGE_SIZES = [25, 50, 100, 250];

const friendly = (value) => String(value || '')
  .trim()
  .toLowerCase()
  .split(/[_\s-]+/)
  .filter(Boolean)
  .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
  .join(' ') || '—';

const money = (value, currency = 'USD') => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '—';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: currency || 'USD', minimumFractionDigits: 2, maximumFractionDigits: 8,
    }).format(numeric);
  } catch {
    return `${numeric.toFixed(2)} ${currency || ''}`.trim();
  }
};

export default function WebullActivityTable({ activities = [], loading = false, emptyMessage = 'No Webull account activity is available.' }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const pageCount = Math.max(1, Math.ceil(activities.length / pageSize));
  useEffect(() => setPage((current) => Math.min(current, pageCount)), [pageCount]);
  const rows = useMemo(
    () => activities.slice((page - 1) * pageSize, page * pageSize),
    [activities, page, pageSize],
  );

  if (loading && !activities.length) return <div className="empty-state"><p>Loading Webull account activity…</p></div>;
  if (!activities.length) return <div className="empty-state"><p>{emptyMessage}</p></div>;

  return (
    <>
      <div className="table-container trading-table">
        <div className="order-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Date / Time (ET)</th>
                <th>Account</th>
                <th>Activity</th>
                <th>Details</th>
                <th>Symbol</th>
                <th>Market</th>
                <th>Amount</th>
                <th>Currency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((activity) => {
                const amount = Number(activity.net_amount);
                return (
                  <tr key={`${activity.account_id}-${activity.id}`}>
                    <td>{activity.biz_time ? formatEasternDateTime(activity.biz_time) : (activity.trade_date || '—')}</td>
                    <td>
                      <strong>{activity.account_label || 'Webull Account'}</strong>
                      <div style={{ fontSize: 11, color: 'var(--text-secondary, #94a3b8)' }}>{activity.account_id_masked || ''}</div>
                    </td>
                    <td>{friendly(activity.activity_type)}</td>
                    <td>{friendly(activity.activity_sub_type)}</td>
                    <td>{activity.symbol || '—'}</td>
                    <td>{friendly(activity.market)}</td>
                    <td style={{ color: amount > 0 ? '#38d39f' : amount < 0 ? '#ef4444' : 'inherit', fontWeight: 700 }}>
                      {money(activity.net_amount, activity.currency)}
                    </td>
                    <td>{activity.currency || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="order-history-pagination">
        <div className="order-history-pagination-info">
          Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, activities.length)} of {activities.length} activities
        </div>
        <div className="order-history-pagination-controls">
          <label className="order-page-size-label">Rows <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
          <button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>‹ Prev</button>
          <span className="order-page-indicator">Page {page} of {pageCount}</span>
          <button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={page === pageCount}>Next ›</button>
        </div>
      </div>
    </>
  );
}
