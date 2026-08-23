import React, { useState, useRef, useEffect, useMemo } from 'react';
import './SearchablePairSelect.css';

const SearchablePairSelect = ({
  value,
  onChange,
  tradingPairs = [],
  includeAllOption = false,
  placeholder = 'Select pair...',
  className = '',
  style = {},
  disabled = false,
  id = undefined
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const containerRef = useRef(null);
  const searchInputRef = useRef(null);
  const listRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Auto-focus search input when opening
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('');
      setHighlightedIndex(0);
      setTimeout(() => {
        if (searchInputRef.current) {
          searchInputRef.current.focus();
        }
      }, 50);
    }
  }, [isOpen]);

  const [favorites, setFavorites] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_favorite_trading_pairs');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const toggleFavorite = (pairId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setFavorites((prev) => {
      const next = prev.includes(pairId)
        ? prev.filter((id) => id !== pairId)
        : [...prev, pairId];
      try {
        localStorage.setItem('crypto_favorite_trading_pairs', JSON.stringify(next));
      } catch (err) {
        console.error('Error saving favorite trading pairs:', err);
      }
      return next;
    });
  };

  // Selected display label
  const selectedLabel = useMemo(() => {
    if (value === 'ALL' || (!value && includeAllOption)) {
      return 'All Trading Pairs';
    }
    const match = tradingPairs.find(p => p.id === value);
    if (match) {
      return match.display_name || match.id;
    }
    return value || placeholder;
  }, [value, tradingPairs, includeAllOption, placeholder]);

  // Filtered and grouped pairs
  const { filteredGroups, flatFilteredList } = useMemo(() => {
    const query = searchQuery.trim().toUpperCase();

    const matchesQuery = (pair) => {
      if (!query) return true;
      const id = (pair.id || '').toUpperCase();
      const name = (pair.display_name || '').toUpperCase();
      const base = (pair.base_asset || '').toUpperCase();
      const quote = (pair.quote_currency || pair.quote_asset || '').toUpperCase();
      return id.includes(query) || name.includes(query) || base.includes(query) || quote.includes(query);
    };

    const pinnedPairs = [];
    const usdPairs = [];
    const usdtPairs = [];
    const otherPairs = [];

    tradingPairs.forEach(p => {
      if (matchesQuery(p)) {
        if (favorites.includes(p.id)) {
          pinnedPairs.push(p);
        }
        const isUsd = p.quote_currency === 'USD' || (p.id && p.id.endsWith('USD') && !p.id.endsWith('USDT'));
        const isUsdt = p.quote_currency === 'USDT' || (p.id && p.id.endsWith('USDT'));
        if (isUsdt) {
          usdtPairs.push(p);
        } else if (isUsd) {
          usdPairs.push(p);
        } else {
          otherPairs.push(p);
        }
      }
    });

    const groups = [];
    const flatList = [];

    if (includeAllOption && (!query || 'ALL TRADING PAIRS'.includes(query) || 'ALL'.includes(query))) {
      groups.push({
        label: 'Global Filter',
        items: [{ id: 'ALL', display_name: 'All Trading Pairs', isAll: true }]
      });
      flatList.push({ id: 'ALL', display_name: 'All Trading Pairs' });
    }

    if (pinnedPairs.length > 0) {
      groups.push({ label: `⭐ Pinned / Favorites (${pinnedPairs.length})`, items: pinnedPairs, isPinnedGroup: true });
      flatList.push(...pinnedPairs);
    }
    if (usdtPairs.length > 0) {
      groups.push({ label: `USDT Pairs (${usdtPairs.length})`, items: usdtPairs });
      flatList.push(...usdtPairs);
    }
    if (usdPairs.length > 0) {
      groups.push({ label: `USD Pairs (${usdPairs.length})`, items: usdPairs });
      flatList.push(...usdPairs);
    }
    if (otherPairs.length > 0) {
      groups.push({ label: `Other Pairs (${otherPairs.length})`, items: otherPairs });
      flatList.push(...otherPairs);
    }

    return { filteredGroups: groups, flatFilteredList: flatList };
  }, [tradingPairs, searchQuery, includeAllOption, favorites]);

  const handleSelect = (pairId) => {
    onChange(pairId);
    setIsOpen(false);
  };

  const handleKeyDown = (e) => {
    if (!isOpen) {
      if (e.key === 'Enter' || e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault();
        setIsOpen(true);
      }
      return;
    }

    if (e.key === 'Escape') {
      e.preventDefault();
      setIsOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightedIndex(prev => (prev + 1 < flatFilteredList.length ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightedIndex(prev => (prev - 1 >= 0 ? prev - 1 : flatFilteredList.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (flatFilteredList[highlightedIndex]) {
        handleSelect(flatFilteredList[highlightedIndex].id);
      }
    }
  };

  return (
    <div
      className={`searchable-pair-select-container ${className} ${isOpen ? 'open' : ''} ${disabled ? 'disabled' : ''}`}
      ref={containerRef}
      style={style}
      id={id}
    >
      {/* Selector Trigger Button */}
      <button
        type="button"
        className="searchable-pair-trigger"
        onClick={() => !disabled && setIsOpen(prev => !prev)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="searchable-pair-trigger-content">
          <span className="searchable-pair-name">{selectedLabel}</span>
          {value && value !== 'ALL' && (
            <span className="searchable-pair-symbol-badge">{value}</span>
          )}
        </span>
        <span className="searchable-pair-arrow">{isOpen ? '▲' : '▼'}</span>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="searchable-pair-dropdown-panel" onKeyDown={handleKeyDown}>
          {/* Search Input */}
          <div className="searchable-pair-search-box">
            <span className="searchable-pair-search-icon">🔍</span>
            <input
              ref={searchInputRef}
              type="text"
              className="searchable-pair-input"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setHighlightedIndex(0);
              }}
              placeholder="Type to filter pairs (e.g. XRP, SOL, USD)..."
              onClick={(e) => e.stopPropagation()}
            />
            {searchQuery && (
              <button
                type="button"
                className="searchable-pair-clear-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setSearchQuery('');
                  searchInputRef.current?.focus();
                }}
                title="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          {/* Pair Options List */}
          <div className="searchable-pair-list" ref={listRef} role="listbox">
            {filteredGroups.length === 0 ? (
              <div className="searchable-pair-no-results">
                No trading pairs match "<strong>{searchQuery}</strong>"
              </div>
            ) : (
              filteredGroups.map((group, groupIdx) => (
                <div key={group.label || groupIdx} className={`searchable-pair-group ${group.isPinnedGroup ? 'pinned-group' : ''}`}>
                  <div className="searchable-pair-group-header">{group.label}</div>
                  {group.items.map((item, itemIdx) => {
                    const isSelected = value === item.id || (!value && item.id === 'ALL');
                    const isHighlighted = flatFilteredList[highlightedIndex]?.id === item.id;
                    const isFav = favorites.includes(item.id);

                    return (
                      <div
                        key={`${group.label}-${item.id}-${itemIdx}`}
                        className={`searchable-pair-option ${isSelected ? 'selected' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                        onClick={() => handleSelect(item.id)}
                        role="option"
                        aria-selected={isSelected}
                      >
                        {!item.isAll && (
                          <button
                            type="button"
                            className={`searchable-pair-star-btn ${isFav ? 'active' : ''}`}
                            onClick={(e) => toggleFavorite(item.id, e)}
                            title={isFav ? 'Unpin favorite pair' : 'Pin pair to top'}
                            aria-label={isFav ? 'Unpin favorite pair' : 'Pin pair to top'}
                          >
                            {isFav ? '⭐' : '☆'}
                          </button>
                        )}
                        <div className="searchable-pair-option-label">
                          <span className="searchable-pair-option-name">{item.display_name || item.id}</span>
                          {!item.isAll && (
                            <span className="searchable-pair-option-code">{item.id}</span>
                          )}
                        </div>
                        {isSelected && <span className="searchable-pair-check">✓</span>}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SearchablePairSelect;
