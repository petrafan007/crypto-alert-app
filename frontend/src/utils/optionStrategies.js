export const OPTION_STRATEGIES = Object.freeze([
  { value: 'SINGLE', label: 'Single Option', legs: 1, description: 'One call or put. Profit and loss follow the selected contract directly.', payoff: 'single' },
  { value: 'COVERED_STOCK', label: 'Covered Option', legs: 2, description: 'Combines 100 shares of stock with one short call to collect premium while capping upside.', payoff: 'covered' },
  { value: 'STRADDLE', label: 'Straddle', legs: 2, description: 'A call and put at the same strike and expiration. It targets a large move in either direction.', payoff: 'valley' },
  { value: 'STRANGLE', label: 'Strangle', legs: 2, description: 'An out-of-the-money call and put at different strikes with the same expiration.', payoff: 'valley' },
  { value: 'VERTICAL', label: 'Vertical', legs: 2, description: 'Two calls or two puts with the same expiration and different strikes. Width controls the strike spacing.', payoff: 'ramp', usesWidth: true },
  { value: 'BUTTERFLY', label: 'Butterfly', legs: 3, description: 'A defined-risk three-strike position that targets a price near the middle strike at expiration; the center leg uses two contracts.', payoff: 'peak', usesWidth: true },
  { value: 'CONDOR', label: 'Condor', legs: 4, description: 'A four-strike defined-risk position with a wider target range than a butterfly.', payoff: 'plateau', usesWidth: true },
  { value: 'COLLAR_WITH_STOCK', label: 'Collar (with Stock)', legs: 3, description: 'Owns 100 shares, buys a protective put, and sells a call to limit both downside and upside.', payoff: 'collar', usesWidth: true },
  { value: 'IRON_BUTTERFLY', label: 'Iron Butterfly', legs: 4, description: 'Sells a call and put at the center strike and buys protective wings at outer strikes.', payoff: 'peak', usesWidth: true },
  { value: 'IRON_CONDOR', label: 'Iron Condor', legs: 4, description: 'Sells an out-of-the-money call and put while buying wider protective wings.', payoff: 'plateau', usesWidth: true },
  { value: 'CALENDAR', label: 'Calendar', legs: 2, description: 'Uses the same option type and strike in two expirations, normally selling the near term and buying the farther term.', payoff: 'curve' },
  { value: 'DIAGONAL', label: 'Diagonal', legs: 2, description: 'Uses the same option type at different strikes and expirations, combining vertical and calendar characteristics.', payoff: 'curve', usesWidth: true },
  { value: 'RATIO', label: 'Ratio', legs: null, description: 'Available in Webull consumer applications, but not documented as an OpenAPI option_strategy value. It is disabled for API order submission.', payoff: 'ratio', disabled: true },
]);

export const optionStrategyDefinition = (value) => (
  OPTION_STRATEGIES.find((strategy) => strategy.value === String(value || '').toUpperCase())
  || OPTION_STRATEGIES[0]
);

const opposite = (side) => (String(side).toUpperCase() === 'BUY' ? 'SELL' : 'BUY');

export const buildOptionStrategyLegs = ({ strategy, chainRows, nextChainRows = [], anchorStrike, optionType, side, width, expiration, expirations }) => {
  const cleanStrategy = String(strategy || 'SINGLE').toUpperCase();
  const rows = [...(chainRows || [])].sort((a, b) => Number(a.strike) - Number(b.strike));
  const anchorIndex = rows.findIndex((row) => Number(row.strike) === Number(anchorStrike));
  if (anchorIndex < 0) throw new Error('The selected strike is no longer present in the active option chain. Refresh and select it again.');
  const step = Math.max(1, Math.min(10, Number(width) || 1));
  const rowAt = (offset) => rows[anchorIndex + offset] || null;
  const cleanSide = String(side || 'BUY').toUpperCase();
  const cleanType = String(optionType || 'CALL').toUpperCase();
  const expirationDates = (expirations || []).map((item) => item.date || item).filter(Boolean);
  const expirationIndex = expirationDates.indexOf(expiration);
  const fartherExpiration = expirationDates[expirationIndex + 1] || null;

  const optionLeg = (row, type, legSide, quantity = 1, legExpiration = expiration) => {
    if (!row) throw new Error(`Width ${step} is not available around the selected strike. Choose a narrower width or show more strikes.`);
    const quoteRow = legExpiration === expiration
      ? row
      : nextChainRows.find((item) => Number(item.strike) === Number(row.strike));
    const quote = type === 'CALL' ? quoteRow?.call : quoteRow?.put;
    if (!quote?.contract_symbol) throw new Error(`No listed ${type.toLowerCase()} contract is available at ${row.strike} for ${legExpiration}.`);
    return {
      instrument_type: 'OPTION',
      side: legSide,
      quantity,
      strike_price: Number(row.strike),
      option_type: type,
      option_expire_date: legExpiration,
      contract_symbol: quote.contract_symbol,
    };
  };
  const stockLeg = (legSide) => ({ instrument_type: 'EQUITY', side: legSide, quantity: 100 });
  const anchor = rowAt(0);

  switch (cleanStrategy) {
    case 'SINGLE': return [optionLeg(anchor, cleanType, cleanSide)];
    case 'COVERED_STOCK': return [stockLeg(cleanSide), optionLeg(anchor, 'CALL', opposite(cleanSide))];
    case 'STRADDLE': return [optionLeg(anchor, 'CALL', cleanSide), optionLeg(anchor, 'PUT', cleanSide)];
    case 'STRANGLE': return [optionLeg(rowAt(step), 'CALL', cleanSide), optionLeg(rowAt(-step), 'PUT', cleanSide)];
    case 'VERTICAL': {
      const direction = cleanType === 'CALL' ? step : -step;
      return [optionLeg(anchor, cleanType, cleanSide), optionLeg(rowAt(direction), cleanType, opposite(cleanSide))];
    }
    case 'BUTTERFLY': return [
      optionLeg(rowAt(-step), cleanType, cleanSide),
      optionLeg(anchor, cleanType, opposite(cleanSide), 2),
      optionLeg(rowAt(step), cleanType, cleanSide),
    ];
    case 'CONDOR': return [
      optionLeg(rowAt(-2 * step), cleanType, cleanSide),
      optionLeg(rowAt(-step), cleanType, opposite(cleanSide)),
      optionLeg(rowAt(step), cleanType, opposite(cleanSide)),
      optionLeg(rowAt(2 * step), cleanType, cleanSide),
    ];
    case 'COLLAR_WITH_STOCK': return [stockLeg(cleanSide), optionLeg(rowAt(-step), 'PUT', cleanSide), optionLeg(rowAt(step), 'CALL', opposite(cleanSide))];
    case 'IRON_BUTTERFLY': return [
      optionLeg(rowAt(-step), 'PUT', opposite(cleanSide)),
      optionLeg(anchor, 'PUT', cleanSide),
      optionLeg(anchor, 'CALL', cleanSide),
      optionLeg(rowAt(step), 'CALL', opposite(cleanSide)),
    ];
    case 'IRON_CONDOR': return [
      optionLeg(rowAt(-2 * step), 'PUT', opposite(cleanSide)),
      optionLeg(rowAt(-step), 'PUT', cleanSide),
      optionLeg(rowAt(step), 'CALL', cleanSide),
      optionLeg(rowAt(2 * step), 'CALL', opposite(cleanSide)),
    ];
    case 'CALENDAR':
      if (!fartherExpiration) throw new Error('A farther expiration is required for a calendar strategy.');
      return [optionLeg(anchor, cleanType, opposite(cleanSide)), optionLeg(anchor, cleanType, cleanSide, 1, fartherExpiration)];
    case 'DIAGONAL':
      if (!fartherExpiration) throw new Error('A farther expiration is required for a diagonal strategy.');
      return [optionLeg(anchor, cleanType, opposite(cleanSide)), optionLeg(rowAt(cleanType === 'CALL' ? step : -step), cleanType, cleanSide, 1, fartherExpiration)];
    default: throw new Error('This strategy is not available through the documented Webull OpenAPI.');
  }
};
