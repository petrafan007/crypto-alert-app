import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from './components/AuthContext';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import './index.css';
import './pages/Trading.theme.css';
import './components/AIAnalysisModal.css';

// Automatically catch dynamic chunk loading errors that occur after new version releases,
// executing a single hard refresh to fetch newly deployed bundles seamlessly.
const isChunkLoadError = (str) => /Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed/i.test(String(str || ''));

window.addEventListener('error', (event) => {
  if (isChunkLoadError(event?.message || event?.filename)) {
    const key = 'chunk_reload_ts';
    const last = Number(sessionStorage.getItem(key) || 0);
    if (Date.now() - last > 10000) {
      sessionStorage.setItem(key, String(Date.now()));
      window.location.reload();
    }
  }
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event?.reason?.message || event?.reason || '';
  if (isChunkLoadError(reason)) {
    const key = 'chunk_reload_ts';
    const last = Number(sessionStorage.getItem(key) || 0);
    if (Date.now() - last > 10000) {
      sessionStorage.setItem(key, String(Date.now()));
      window.location.reload();
    }
  }
});

// Register the PWA service worker (root scope, so it covers every route).
// Static assets are cached for fast repeat loads; API traffic and pages
// always go to the network. A failed registration must never break the app.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      console.warn('Service worker registration failed:', error);
    });
  });
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary fallbackTitle="Crypto & Securities Dashboard Error" fallbackMessage="An error occurred while loading the application interface. Please reload to reconnect.">
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
