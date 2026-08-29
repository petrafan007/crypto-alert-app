/**
 * Global toast notification helper.
 * Dispatches a custom event caught by ToastNotifications.jsx.
 *
 * @param {string} message - The notification text.
 * @param {'info'|'success'|'warning'|'error'} [type='info'] - The notification type.
 * @param {Object} [extra={}] - Optional metadata (symbol, id, timeout, etc.).
 */
export function showAppToast(message, type = 'info', extra = {}) {
  if (!message || typeof window === 'undefined') return;
  const category = (type === 'error' || type === 'danger') ? 'error'
    : type === 'success' ? 'success'
    : type === 'warning' ? 'warning'
    : 'info';

  window.dispatchEvent(new CustomEvent('app:new-toast', {
    detail: {
      message,
      category,
      type,
      ...extra,
    }
  }));
}
