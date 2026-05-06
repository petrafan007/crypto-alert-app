/**
 * Utility functions for exchange-specific operations
 */

export const getTradeUrl = (symbol, exchange = 'binance') => {
  const baseSymbol = symbol.replace(/[^a-zA-Z]/g, ''); // Remove any non-letter characters
  
  switch(exchange.toLowerCase()) {
    case 'binance':
    default:
      return `https://www.binance.us/en/trade/${baseSymbol}_USDT`;
  }
};

export const getExchangeName = (exchange = 'binance') => {
  return exchange.charAt(0).toUpperCase() + exchange.slice(1);
};
