import React, { useState, useEffect, useRef } from 'react';
import './DashboardWidgetGrid.css';

const DEFAULT_WIDGETS = [
  { id: 'portfolio_value', title: 'Portfolio Value', width: 'sm', height: 'auto' },
  { id: 'fear_greed', title: 'Fear & Greed Index', width: 'sm', height: 'auto' },
  { id: 'cbbi', title: 'CBBI Bull Run Index', width: 'sm', height: 'auto' },
  { id: 'staking', title: 'Staking Rewards', width: 'sm', height: 'auto' },
  { id: 'performance', title: '7-Day Performance', width: 'sm', height: 'auto' },
  { id: 'allocations', title: 'Asset Allocations', width: 'md', height: 'auto' },
  { id: 'trend', title: 'Portfolio Trend', width: 'md', height: 'auto' },
];

const STORAGE_KEY = 'crypto_dashboard_widget_layout_v1';

const DashboardWidgetGrid = ({
  isLightMode,
  renderWidgetContent
}) => {
  const [isEditMode, setIsEditMode] = useState(false);
  const [widgets, setWidgets] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          // Merge with any new default widgets that might not be in saved list
          const savedIds = new Set(parsed.map(w => w.id));
          const missing = DEFAULT_WIDGETS.filter(d => !savedIds.has(d.id));
          return [...parsed, ...missing];
        }
      }
    } catch (e) {
      console.error('Error loading dashboard layout:', e);
    }
    return DEFAULT_WIDGETS;
  });

  const [hiddenWidgetIds, setHiddenWidgetIds] = useState(() => {
    try {
      const savedHidden = localStorage.getItem(`${STORAGE_KEY}_hidden`);
      if (savedHidden) {
        return JSON.parse(savedHidden) || [];
      }
    } catch (e) { }
    return [];
  });

  const [draggedId, setDraggedId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);
  const [showAddMenu, setShowAddMenu] = useState(false);
  const addMenuRef = useRef(null);

  // Save to localStorage
  const saveLayout = (newWidgets, newHidden = hiddenWidgetIds) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newWidgets));
      localStorage.setItem(`${STORAGE_KEY}_hidden`, JSON.stringify(newHidden));
    } catch (e) {
      console.error('Failed to save dashboard layout:', e);
    }
  };

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

  const handleResetLayout = () => {
    setWidgets(DEFAULT_WIDGETS);
    setHiddenWidgetIds([]);
    saveLayout(DEFAULT_WIDGETS, []);
  };

  const handleHideWidget = (id) => {
    const updatedHidden = [...new Set([...hiddenWidgetIds, id])];
    setHiddenWidgetIds(updatedHidden);
    saveLayout(widgets, updatedHidden);
  };

  const handleUnhideWidget = (id) => {
    const updatedHidden = hiddenWidgetIds.filter(hId => hId !== id);
    setHiddenWidgetIds(updatedHidden);
    saveLayout(widgets, updatedHidden);
    setShowAddMenu(false);
  };

  const handleWidthChange = (id, newWidth) => {
    const updated = widgets.map(w => (w.id === id ? { ...w, width: newWidth } : w));
    setWidgets(updated);
    saveLayout(updated);
  };

  // Drag and drop handlers
  const handleDragStart = (e, id) => {
    setDraggedId(id);
    e.dataTransfer.setData('text/plain', id);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e, targetId) => {
    e.preventDefault();
    if (draggedId && draggedId !== targetId) {
      setDragOverId(targetId);
    }
  };

  const handleDragLeave = (e, targetId) => {
    if (dragOverId === targetId) {
      setDragOverId(null);
    }
  };

  const handleDrop = (e, targetId) => {
    e.preventDefault();
    setDragOverId(null);
    if (!draggedId || draggedId === targetId) return;

    const sourceIndex = widgets.findIndex(w => w.id === draggedId);
    const targetIndex = widgets.findIndex(w => w.id === targetId);

    if (sourceIndex >= 0 && targetIndex >= 0) {
      const newWidgets = [...widgets];
      const [moved] = newWidgets.splice(sourceIndex, 1);
      newWidgets.splice(targetIndex, 0, moved);
      setWidgets(newWidgets);
      saveLayout(newWidgets);
    }
    setDraggedId(null);
  };

  const handleDragEnd = () => {
    setDraggedId(null);
    setDragOverId(null);
  };

  const hiddenWidgetsList = DEFAULT_WIDGETS.filter(w => hiddenWidgetIds.includes(w.id));
  const visibleWidgets = widgets.filter(w => !hiddenWidgetIds.includes(w.id));

  return (
    <div className={`dashboard-widget-grid-container ${isEditMode ? 'edit-mode-active' : ''}`}>
      {/* Top Controls Bar */}
      <div className="dashboard-grid-toolbar">
        <div className="dashboard-grid-toolbar-left">
          <button
            type="button"
            className={`dashboard-edit-toggle-btn ${isEditMode ? 'active' : ''}`}
            onClick={() => setIsEditMode(prev => !prev)}
            title="Customize dashboard panel positions and sizes"
          >
            {isEditMode ? '✓ Done Editing' : '✏️ Customize Layout'}
          </button>

          {isEditMode && (
            <span className="dashboard-edit-hint">
              Drag by handle (⠿) to reorder, resize using width toggles, or click (✕) to hide.
            </span>
          )}
        </div>

        {isEditMode && (
          <div className="dashboard-grid-toolbar-right">
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

      {/* Dynamic Widget Grid Canvas */}
      <div className="dashboard-widget-grid">
        {visibleWidgets.map((widget) => {
          const isDragging = draggedId === widget.id;
          const isDropTarget = dragOverId === widget.id;

          return (
            <div
              key={widget.id}
              className={`dashboard-widget-card size-${widget.width || 'sm'} ${isDragging ? 'is-dragging' : ''} ${isDropTarget ? 'is-drop-target' : ''}`}
              onDragOver={(e) => isEditMode && handleDragOver(e, widget.id)}
              onDragLeave={(e) => isEditMode && handleDragLeave(e, widget.id)}
              onDrop={(e) => isEditMode && handleDrop(e, widget.id)}
            >
              {/* Edit Mode Overlay & Controls */}
              {isEditMode && (
                <div className="dashboard-widget-edit-header">
                  <div
                    className="dashboard-widget-drag-handle"
                    draggable
                    onDragStart={(e) => handleDragStart(e, widget.id)}
                    onDragEnd={handleDragEnd}
                    title="Click and drag to reposition panel"
                  >
                    <span className="drag-icon">⠿</span>
                    <span className="drag-title">{widget.title}</span>
                  </div>

                  <div className="dashboard-widget-size-controls">
                    <button
                      type="button"
                      className={`size-btn ${widget.width === 'sm' ? 'active' : ''}`}
                      onClick={() => handleWidthChange(widget.id, 'sm')}
                      title="Compact (1 column)"
                    >
                      1x
                    </button>
                    <button
                      type="button"
                      className={`size-btn ${widget.width === 'md' ? 'active' : ''}`}
                      onClick={() => handleWidthChange(widget.id, 'md')}
                      title="Wide (2 columns)"
                    >
                      2x
                    </button>
                    <button
                      type="button"
                      className={`size-btn ${widget.width === 'lg' ? 'active' : ''}`}
                      onClick={() => handleWidthChange(widget.id, 'lg')}
                      title="Full Width"
                    >
                      3x
                    </button>
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

              {/* Widget Body Content */}
              <div className="dashboard-widget-body">
                {renderWidgetContent(widget.id)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DashboardWidgetGrid;
