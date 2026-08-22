import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Responsive, WidthProvider } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import './DashboardWidgetGrid.css';

const ResponsiveGridLayout = WidthProvider(Responsive);

const WIDGETS = [
  { id: 'portfolio_value', title: 'Portfolio Value' },
  { id: 'fear_greed', title: 'Fear & Greed Index' },
  { id: 'cbbi', title: 'CBBI Bull Run Index' },
  { id: 'staking', title: 'Staking Rewards' },
  { id: 'performance', title: '7-Day Performance' },
  { id: 'allocations', title: 'Asset Allocations' },
  { id: 'trend', title: 'Portfolio Trend' },
  { id: 'top_movers', title: 'Top Gainers & Losers' },
  { id: 'recent_trades', title: 'Recent Trade History' },
  { id: 'ai_pulse', title: 'AI Copilot Market Pulse' },
  { id: 'staking_rewards', title: 'Staking Yield Tracker' },
  { id: 'risk_monitor', title: 'Portfolio Risk Monitor' },
  { id: 'quick_trade', title: 'Quick Trade Terminal' },
  { id: 'gas_monitor', title: 'Network Gas & Fees' }
];

const NEW_WIDGET_IDS = [
  'top_movers',
  'recent_trades',
  'ai_pulse',
  'staking_rewards',
  'risk_monitor',
  'quick_trade',
  'gas_monitor'
];

const getWidgetBounds = (id) => {
  switch (id) {
    case 'allocations': return { minW: 3, minH: 3 };
    case 'trend': return { minW: 4, minH: 3 };
    case 'performance': return { minW: 3, minH: 2 };
    case 'fear_greed': return { minW: 2, minH: 3 };
    case 'cbbi': return { minW: 2, minH: 3 };
    case 'portfolio_value': return { minW: 2, minH: 3 };
    case 'staking': return { minW: 2, minH: 3 };
    case 'top_movers': return { minW: 3, minH: 3 };
    case 'recent_trades': return { minW: 3, minH: 3 };
    case 'ai_pulse': return { minW: 3, minH: 3 };
    case 'staking_rewards': return { minW: 2, minH: 3 };
    case 'risk_monitor': return { minW: 2, minH: 3 };
    case 'quick_trade': return { minW: 3, minH: 3 };
    case 'gas_monitor': return { minW: 2, minH: 3 };
    default: return { minW: 2, minH: 3 };
  }
};

const mapLayoutBounds = (layout) => layout.map(item => ({ ...item, ...getWidgetBounds(item.i) }));

const DEFAULT_LAYOUTS = {
  lg: mapLayoutBounds([
    { i: 'allocations', x: 0, y: 0, w: 4, h: 4 },
    { i: 'trend', x: 4, y: 0, w: 8, h: 4 },
    { i: 'portfolio_value', x: 0, y: 4, w: 3, h: 3 },
    { i: 'fear_greed', x: 3, y: 4, w: 3, h: 3 },
    { i: 'cbbi', x: 6, y: 4, w: 3, h: 3 },
    { i: 'staking', x: 9, y: 4, w: 3, h: 3 },
    { i: 'performance', x: 0, y: 7, w: 12, h: 2 },
    { i: 'top_movers', x: 0, y: 9, w: 4, h: 3 },
    { i: 'recent_trades', x: 4, y: 9, w: 4, h: 3 },
    { i: 'ai_pulse', x: 8, y: 9, w: 4, h: 3 },
    { i: 'staking_rewards', x: 0, y: 12, w: 3, h: 3 },
    { i: 'risk_monitor', x: 3, y: 12, w: 3, h: 3 },
    { i: 'quick_trade', x: 6, y: 12, w: 3, h: 3 },
    { i: 'gas_monitor', x: 9, y: 12, w: 3, h: 3 }
  ]),
  md: mapLayoutBounds([
    { i: 'allocations', x: 0, y: 0, w: 4, h: 4 },
    { i: 'trend', x: 4, y: 0, w: 6, h: 4 },
    { i: 'portfolio_value', x: 0, y: 4, w: 5, h: 3 },
    { i: 'fear_greed', x: 5, y: 4, w: 5, h: 3 },
    { i: 'cbbi', x: 0, y: 7, w: 5, h: 3 },
    { i: 'staking', x: 5, y: 7, w: 5, h: 3 },
    { i: 'performance', x: 0, y: 10, w: 10, h: 2 },
    { i: 'top_movers', x: 0, y: 12, w: 5, h: 3 },
    { i: 'recent_trades', x: 5, y: 12, w: 5, h: 3 },
    { i: 'ai_pulse', x: 0, y: 15, w: 5, h: 3 },
    { i: 'staking_rewards', x: 5, y: 15, w: 5, h: 3 },
    { i: 'risk_monitor', x: 0, y: 18, w: 5, h: 3 },
    { i: 'quick_trade', x: 5, y: 18, w: 5, h: 3 },
    { i: 'gas_monitor', x: 0, y: 21, w: 5, h: 3 }
  ]),
  sm: mapLayoutBounds([
    { i: 'allocations', x: 0, y: 0, w: 6, h: 4 },
    { i: 'trend', x: 0, y: 4, w: 6, h: 4 },
    { i: 'portfolio_value', x: 0, y: 8, w: 6, h: 3 },
    { i: 'fear_greed', x: 0, y: 11, w: 6, h: 3 },
    { i: 'cbbi', x: 0, y: 14, w: 6, h: 3 },
    { i: 'staking', x: 0, y: 17, w: 6, h: 3 },
    { i: 'performance', x: 0, y: 20, w: 6, h: 2 },
    { i: 'top_movers', x: 0, y: 22, w: 6, h: 3 },
    { i: 'recent_trades', x: 0, y: 25, w: 6, h: 3 },
    { i: 'ai_pulse', x: 0, y: 28, w: 6, h: 3 },
    { i: 'staking_rewards', x: 0, y: 31, w: 6, h: 3 },
    { i: 'risk_monitor', x: 0, y: 34, w: 6, h: 3 },
    { i: 'quick_trade', x: 0, y: 37, w: 6, h: 3 },
    { i: 'gas_monitor', x: 0, y: 40, w: 6, h: 3 }
  ])
};

const STORAGE_KEY = 'crypto_dashboard_widget_layout_v1_70';
const HIDDEN_STORAGE_KEY = 'crypto_dashboard_widget_hidden_v1_70';

const DashboardWidgetGrid = ({
  isLightMode,
  renderWidgetContent,
  onEditPerformanceCoins
}) => {
  const [isEditMode, setIsEditMode] = useState(false);
  const [layouts, setLayouts] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch (e) {
      console.error('Error loading layouts:', e);
    }
    return DEFAULT_LAYOUTS;
  });

  const [hiddenWidgetIds, setHiddenWidgetIds] = useState(() => {
    try {
      const saved = localStorage.getItem(HIDDEN_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        // Ensure new widgets are included in hidden list if not already explicitly saved
        return Array.from(new Set([...(parsed || []), ...NEW_WIDGET_IDS]));
      }
    } catch (e) { }
    return [...NEW_WIDGET_IDS];
  });

  const [initialSnapshot, setInitialSnapshot] = useState(null);
  const [history, setHistory] = useState([]);
  const [saveToast, setSaveToast] = useState('');
  const [showAddMenu, setShowAddMenu] = useState(false);
  const addMenuRef = useRef(null);

  // Close add menu on outside click
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (addMenuRef.current && !addMenuRef.current.contains(e.target)) {
        setShowAddMenu(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Enter edit mode
  const handleToggleEditMode = () => {
    if (!isEditMode) {
      // Starting edit mode: record initial snapshot and clear history
      setInitialSnapshot({
        layouts: JSON.parse(JSON.stringify(layouts)),
        hiddenWidgetIds: [...hiddenWidgetIds]
      });
      setHistory([]);
      setIsEditMode(true);
    } else {
      // Done editing: save and exit
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts));
      localStorage.setItem(HIDDEN_STORAGE_KEY, JSON.stringify(hiddenWidgetIds));
      setIsEditMode(false);
      setHistory([]);
      setInitialSnapshot(null);
    }
  };

  // Helper to push history before a mutation
  const pushHistory = (currentLayouts, currentHidden) => {
    setHistory(prev => [
      ...prev.slice(-4), // keep last 5 total
      {
        layouts: JSON.parse(JSON.stringify(currentLayouts || layouts)),
        hiddenWidgetIds: [...(currentHidden || hiddenWidgetIds)]
      }
    ]);
  };

  // Explicit Save button
  const handleSaveOnly = () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts));
    localStorage.setItem(HIDDEN_STORAGE_KEY, JSON.stringify(hiddenWidgetIds));
    setInitialSnapshot({
      layouts: JSON.parse(JSON.stringify(layouts)),
      hiddenWidgetIds: [...hiddenWidgetIds]
    });
    setSaveToast('✓ Saved!');
    setTimeout(() => setSaveToast(''), 2000);
  };

  // Undo button (rolls back to last state in history stack)
  const handleUndo = () => {
    if (history.length === 0) return;
    const previousState = history[history.length - 1];
    setHistory(prev => prev.slice(0, prev.length - 1));
    setLayouts(previousState.layouts);
    setHiddenWidgetIds(previousState.hiddenWidgetIds);
  };

  // Cancel button (discards all changes since edit mode started)
  const handleCancel = () => {
    if (initialSnapshot) {
      setLayouts(initialSnapshot.layouts);
      setHiddenWidgetIds(initialSnapshot.hiddenWidgetIds);
    }
    setIsEditMode(false);
    setHistory([]);
    setInitialSnapshot(null);
  };

  const handleLayoutChange = (layout, allLayouts) => {
    if (!isEditMode) return;
    pushHistory(layouts, hiddenWidgetIds);

    const mappedLayouts = {};
    for (const [bp, l] of Object.entries(allLayouts)) {
      mappedLayouts[bp] = mapLayoutBounds(l);
    }
    setLayouts(mappedLayouts);
  };

  const handleResetLayout = () => {
    pushHistory(layouts, hiddenWidgetIds);
    setLayouts(DEFAULT_LAYOUTS);
    setHiddenWidgetIds(NEW_WIDGET_IDS);
  };

  const handleHideWidget = (id) => {
    pushHistory(layouts, hiddenWidgetIds);
    const updated = [...new Set([...hiddenWidgetIds, id])];
    setHiddenWidgetIds(updated);
  };

  const handleUnhideWidget = (id) => {
    pushHistory(layouts, hiddenWidgetIds);
    const updated = hiddenWidgetIds.filter(h => h !== id);
    setHiddenWidgetIds(updated);
    setShowAddMenu(false);
  };

  const hiddenWidgetsList = WIDGETS.filter(w => hiddenWidgetIds.includes(w.id));
  const visibleWidgets = WIDGETS.filter(w => !hiddenWidgetIds.includes(w.id));

  const portalTarget = document.getElementById('navbar-customize-portal');

  const customizeBtn = (
    <button
      type="button"
      className={portalTarget ? `nav-link ${isEditMode ? 'active' : ''}` : `dashboard-edit-toggle-btn ${isEditMode ? 'active' : ''}`}
      onClick={handleToggleEditMode}
      title="Customize dashboard panel positions and sizes"
    >
      {isEditMode ? '✓ Done Editing' : '✏️ Customize Layout'}
    </button>
  );

  return (
    <div className={`dashboard-widget-grid-container ${isEditMode ? 'edit-mode-active' : ''}`}>
      {portalTarget && createPortal(customizeBtn, portalTarget)}

      {/* Top Controls Bar */}
      {(isEditMode || !portalTarget) && (
      <div className="dashboard-grid-toolbar">
        <div className="dashboard-grid-toolbar-left">
          {!portalTarget && customizeBtn}

          {isEditMode && (
            <span className="dashboard-edit-hint">
              Drag by handle (⠿) to reorder, drag any corner/edge to resize, or click (✕) to hide.
            </span>
          )}
        </div>

        {isEditMode && (
          <div className="dashboard-grid-toolbar-right">
            {/* Save Button */}
            <button
              type="button"
              className="dashboard-save-layout-btn"
              onClick={handleSaveOnly}
              title="Save current layout changes"
            >
              {saveToast || '💾 Save'}
            </button>

            {/* Undo Button */}
            <button
              type="button"
              className="dashboard-undo-layout-btn"
              onClick={handleUndo}
              disabled={history.length === 0}
              title={history.length > 0 ? `Undo last change (${history.length} in history)` : 'No actions to undo'}
            >
              ↩ Undo {history.length > 0 && `(${history.length})`}
            </button>

            {/* Cancel Button */}
            <button
              type="button"
              className="dashboard-cancel-layout-btn"
              onClick={handleCancel}
              title="Discard all changes and exit edit mode"
            >
              ✕ Cancel
            </button>

            {/* Add / Unhide Widgets Dropdown */}
            <div className="dashboard-add-widgets-wrapper" ref={addMenuRef}>
              <button
                type="button"
                className="dashboard-add-widget-btn"
                onClick={() => setShowAddMenu(prev => !prev)}
              >
                + Add / Restore Panels {hiddenWidgetsList.length > 0 && `(${hiddenWidgetsList.length})`}
              </button>

              {showAddMenu && (
                <div className="dashboard-add-widget-dropdown">
                  <div className="dashboard-add-widget-header">Available Panels</div>
                  {hiddenWidgetsList.length === 0 ? (
                    <div className="dashboard-no-hidden-msg">All panels are currently visible</div>
                  ) : (
                    hiddenWidgetsList.map(hw => (
                      <div
                        key={hw.id}
                        className="dashboard-add-widget-item"
                        onClick={() => handleUnhideWidget(hw.id)}
                      >
                        <span>{hw.title}</span>
                        <span className="dashboard-add-icon">＋ Restore</span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* Reset Layout */}
            <button
              type="button"
              className="dashboard-reset-layout-btn"
              onClick={handleResetLayout}
              title="Reset dashboard panels to default arrangement"
            >
              ↺ Reset Default
            </button>
          </div>
        )}
      </div>
      )}

      {/* React Grid Layout Canvas */}
      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
        rowHeight={80}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".dashboard-widget-drag-handle"
        isDraggable={isEditMode}
        isResizable={isEditMode}
        resizeHandles={['se', 'sw', 'ne', 'nw', 'e', 'w', 'n', 's']}
        margin={[16, 16]}
        containerPadding={[0, 0]}
      >
        {visibleWidgets.map(widget => (
          <div key={widget.id} className="dashboard-widget-card">
            {isEditMode && (
              <div className="dashboard-widget-edit-header">
                <div className="dashboard-widget-drag-handle" title="Drag to reorder">
                  <span className="drag-icon">⠿</span>
                  <span className="drag-title">{widget.title}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {widget.id === 'performance' && (
                    <button
                      type="button"
                      className="dashboard-widget-edit-coins-btn"
                      onClick={() => onEditPerformanceCoins?.()}
                      title="Filter visible coins in Coin Performance"
                      style={{
                        background: 'rgba(56, 189, 248, 0.15)',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                        color: '#38bdf8',
                        cursor: 'pointer',
                        fontSize: '13px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        lineHeight: 1,
                        transition: 'all 0.2s ease'
                      }}
                    >
                      ✏️
                    </button>
                  )}
                  <button
                    type="button"
                    className="dashboard-widget-hide-btn"
                    onClick={() => handleHideWidget(widget.id)}
                    title="Hide panel from view"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}
            <div className="dashboard-widget-body">
              {renderWidgetContent(widget.id)}
            </div>
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
};

export default DashboardWidgetGrid;

