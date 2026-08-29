import React, { useState, useRef, useEffect, useMemo } from 'react';
import './SearchablePairSelect.css';

const SearchablePairSelect = ({
  value,
  onChange,
  tradingPairs = [],
  includeAllOption = false,
  placeholder = 'Select pair...',
  mode = 'crypto',
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

  const storageKey = mode === 'traditional' ? 'traditional_favorite_instruments' : 'crypto_favorite_trading_pairs';

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
      const saved = localStorage.getItem(storageKey);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Re-read favorites when storageKey/mode changes
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      setFavorites(saved ? JSON.parse(saved) : []);
    } catch {
      setFavorites([]);
    }
  }, [storageKey]);

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
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch (err) {
        console.error('Error saving favorite trading instruments:', err);
      }
      return next;
    });
  };

  // Selected display label
  const selectedLabel = useMemo(() => {
    if (value === 'ALL' || (!value && includeAllOption)) {
      return mode === 'traditional' ? 'All Instruments' : 'All Trading Pairs';
    }
    const match = tradingPairs.find(p => (p.id || p.symbol) === value);
    if (match) {
      return match.display_name || match.name ? `${match.symbol || match.id} — ${match.name || match.display_name}` : (match.id || match.symbol);
    }
    return value || placeholder;
  }, [value, tradingPairs, includeAllOption, placeholder, mode]);

  // Filtered and grouped pairs/instruments
  const { filteredGroups, flatFilteredList } = useMemo(() => {
    const query = searchQuery.trim().toUpperCase();

    const matchesQuery = (item) => {
      if (!query) return true;
      const id = (item.id || item.symbol || '').toUpperCase();
      const name = (item.display_name || item.name || '').toUpperCase();
      const base = (item.base_asset || '').toUpperCase();
      const quote = (item.quote_currency || item.quote_asset || '').toUpperCase();
      return id.includes(query) || name.includes(query) || base.includes(query) || quote.includes(query);
    };

    const groups = [];
    const flatList = [];

    if (mode === 'traditional') {
      const pinnedStocks = [];
      const holdingStocks = [];
      const regularStocks = [];
      let exactMatchFound = false;

      tradingPairs.forEach((item) => {
        const itemId = item.id || item.symbol;
        if (itemId.toUpperCase() === query) {
          exactMatchFound = true;
        }
        if (matchesQuery(item)) {
          if (favorites.includes(itemId)) {
            pinnedStocks.push(item);
          }
          if (item.isHolding || item.is_holding) {
            holdingStocks.push(item);
          } else {
            regularStocks.push(item);
          }
        }
      });

      // If user typed a custom ticker that isn't in predefined list, allow instant loading
      if (query && !exactMatchFound && query.length >= 1 && /^[A-Z0-9.\-_]{1,12}$/.test(query)) {
        const customItem = {
          id: query,
          symbol: query,
          display_name: `${query} (Load Ticker)`,
          isCustom: true,
        };
        groups.push({
          label: 'Custom Ticker Search',
          items: [customItem],
        });
        flatList.push(customItem);
      }

      if (pinnedStocks.length > 0) {
        groups.push({ label: `⭐ Pinned / Favorites (${pinnedStocks.length})`, items: pinnedStocks, isPinnedGroup: true });
        flatList.push(...pinnedStocks);
      }
      if (holdingStocks.length > 0) {
        groups.push({ label: `💼 My Holdings (${holdingStocks.length})`, items: holdingStocks });
        flatList.push(...holdingStocks);
      }
      if (regularStocks.length > 0) {
        groups.push({ label: `🏛️ Stocks & ETFs (${regularStocks.length})`, items: regularStocks });
        flatList.push(...regularStocks);
      }

      return { filteredGroups: groups, flatFilteredList: flatList };
    }

    // Default Crypto Mode
    const pinnedPairs = [];
    const usdPairs = [];
    const usdtPairs = [];
    const otherPairs = [];
    let exactCryptoMatch = false;

    tradingPairs.forEach(p => {
      const pId = (p.id || p.symbol || '');
      if (pId.toUpperCase() === query || pId.toUpperCase() === `${query}USD` || pId.toUpperCase() === `${query}USDT`) {
        exactCryptoMatch = true;
      }
      if (matchesQuery(p)) {
        if (favorites.includes(pId)) {
          pinnedPairs.push(p);
        }
        const isUsd = p.quote_currency === 'USD' || (pId.endsWith('USD') && !pId.endsWith('USDT'));
        const isUsdt = p.quote_currency === 'USDT' || (pId.endsWith('USDT'));
        if (isUsdt) {
          usdtPairs.push(p);
        } else if (isUsd) {
          usdPairs.push(p);
        } else {
          otherPairs.push(p);
        }
      }
    });

    if (includeAllOption && (!query || 'ALL TRADING PAIRS'.includes(query) || 'ALL'.includes(query))) {
      groups.push({
        label: 'Global Filter',
        items: [{ id: 'ALL', display_name: 'All Trading Pairs', isAll: true }]
      });
      flatList.push({ id: 'ALL', display_name: 'All Trading Pairs' });
    }

    // Custom Crypto Lookup if not matching exactly
    if (query && !exactCryptoMatch && query.length >= 2 && /^[A-Z0-9]{2,10}$/.test(query)) {
      const resolvedCustom = query.endsWith('USD') || query.endsWith('USDT') ? query : `${query}USD`;
      const customItem = {
        id: resolvedCustom,
        symbol: resolvedCustom,
        display_name: `${resolvedCustom} (Load Pair)`,
        isCustom: true,
      };
      groups.push({
        label: 'Custom Pair Search',
        items: [customItem],
      });
      flatList.push(customItem);
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
  }, [tradingPairs, searchQuery, includeAllOption, favorites, mode]);

  const handleSelect = (pairId) => {
    const selectedItem = flatFilteredList.find((item) => item.id === pairId) || null;
    onChange(pairId, selectedItem);
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
              placeholder={placeholder || (mode === 'traditional' ? 'Type to filter stocks (e.g. AAPL, NVDA, SPY)...' : 'Type to filter pairs (e.g. XRP, SOL, USD)...')}
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
                {mode === 'traditional' ? 'No stocks or ETFs match' : 'No trading pairs match'} "<strong>{searchQuery}</strong>"
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
                        <div className="searchable-pair-option-left">
                          {!item.isAll ? (
                            <button
                              type="button"
                              className={`searchable-pair-star-btn ${isFav ? 'active' : ''}`}
                              onClick={(e) => toggleFavorite(item.id, e)}
                              title={isFav ? 'Unpin favorite pair' : 'Pin pair to top'}
                              aria-label={isFav ? 'Unpin favorite pair' : 'Pin pair to top'}
                            >
                              {isFav ? '⭐' : '☆'}
                            </button>
                          ) : (
                            <span className="searchable-pair-star-placeholder" />
                          )}
                          <div className="searchable-pair-option-label">
                            <span className="searchable-pair-option-name">{item.display_name || item.id}</span>
                            {!item.isAll && (
                              <span className="searchable-pair-option-code">{item.id}</span>
                            )}
                          </div>
                        </div>
                        <div className="searchable-pair-option-right">
                          {isSelected && <span className="searchable-pair-check">✓</span>}
                        </div>
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
