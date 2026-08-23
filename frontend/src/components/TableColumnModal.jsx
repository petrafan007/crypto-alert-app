import React, { useState, useEffect } from 'react';
import './TableColumnModal.css';

export default function TableColumnModal({
  isOpen,
  onClose,
  tableType = 'portfolio',
  columnDefinitions = {},
  visibleColumns = [],
  onSave,
  onReset
}) {
  const [selectedColumns, setSelectedColumns] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    if (isOpen) {
      setSelectedColumns([...visibleColumns]);
      setSearchQuery('');
    }
  }, [isOpen, visibleColumns]);

  if (!isOpen) return null;

  const isPortfolio = tableType === 'portfolio';
  const tableTitle = isPortfolio ? 'Portfolio' : 'Watchlist';

  const handleToggleColumn = (key, isRequired) => {
    if (isRequired) return; // Cannot toggle locked required columns
    setSelectedColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const handleSelectAll = () => {
    const allKeys = Object.keys(columnDefinitions);
    setSelectedColumns(allKeys);
  };

  const handleSave = () => {
    onSave(selectedColumns);
    onClose();
  };

  const handleResetDefaults = () => {
    onReset();
    onClose();
  };

  const columnEntries = Object.entries(columnDefinitions).filter(([key, def]) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase().trim();
    return (
      key.toLowerCase().includes(q) ||
      (def.label && def.label.toLowerCase().includes(q))
    );
  });

  return (
    <div className="table-column-modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="table-column-modal" role="dialog" aria-labelledby="column-modal-title">
        <div className="table-column-modal-header">
          <div className="table-column-modal-title-wrap">
            <span className="table-column-modal-icon">✏️</span>
            <div>
              <h3 id="column-modal-title">Customize {tableTitle} Columns</h3>
              <p className="table-column-modal-subtitle">
                Select which columns appear in your {tableTitle.toLowerCase()} table. Locked columns are required.
              </p>
            </div>
          </div>
          <button className="table-column-modal-close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {/* Search & Quick Actions */}
        <div className="table-column-modal-controls">
          <div className="table-column-search-wrap">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              placeholder="Search columns..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="table-column-search-input"
            />
            {searchQuery && (
              <button
                type="button"
                className="search-clear-btn"
                onClick={() => setSearchQuery('')}
              >
                ✕
              </button>
            )}
          </div>
          <div className="table-column-quick-links">
            <button type="button" onClick={handleSelectAll} className="quick-action-btn">
              Select All
            </button>
          </div>
        </div>

        {/* Columns Grid */}
        <div className="table-column-options-list">
          {columnEntries.map(([key, def]) => {
            const isChecked = selectedColumns.includes(key) || def.required;
            const isRequired = !!def.required;

            return (
              <label
                key={key}
                className={`table-column-option-card ${isChecked ? 'active' : ''} ${isRequired ? 'locked' : ''}`}
              >
                <div className="table-column-option-left">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={isRequired}
                    onChange={() => handleToggleColumn(key, isRequired)}
                    className="table-column-checkbox"
                  />
                  <div className="table-column-option-text">
                    <span className="table-column-name">{def.label || key}</span>
                    {def.description && (
                      <span className="table-column-desc">{def.description}</span>
                    )}
                  </div>
                </div>
                {isRequired && (
                  <span className="table-column-locked-badge" title="Required column, cannot be removed">
                    🔒 Locked
                  </span>
                )}
              </label>
            );
          })}
        </div>

        {/* Footer Actions */}
        <div className="table-column-modal-footer">
          <button
            type="button"
            className="btn btn-secondary reset-defaults-btn"
            onClick={handleResetDefaults}
          >
            ↺ Reset to Default
          </button>
          <div className="footer-right-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary apply-columns-btn"
              onClick={handleSave}
            >
              Apply Columns
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
