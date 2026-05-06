/**
 * Technical Indicators Calculation Utilities
 * All calculations use OHLCV candlestick data from Binance.US klines
 */

/**
 * Calculate Simple Moving Average (SMA)
 * @param {Array} data - Array of {time, close} objects
 * @param {number} period - MA period (e.g., 7, 25, 99)
 * @returns {Array} Array of {time, value} for MA line
 */
export function calculateSMA(data, period) {
  if (!data || data.length < period) return [];
  
  const result = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close;
    }
    result.push({
      time: data[i].time,
      value: sum / period
    });
  }
  return result;
}

/**
 * Calculate Exponential Moving Average (EMA)
 * @param {Array} data - Array of {time, close} objects
 * @param {number} period - EMA period
 * @returns {Array} Array of {time, value} for EMA line
 */
export function calculateEMA(data, period) {
  if (!data || data.length < period) return [];
  
  const k = 2 / (period + 1);
  const result = [];
  
  // Start with SMA for first value
  let ema = 0;
  for (let i = 0; i < period; i++) {
    ema += data[i].close;
  }
  ema = ema / period;
  result.push({ time: data[period - 1].time, value: ema });
  
  // Calculate EMA for remaining values
  for (let i = period; i < data.length; i++) {
    ema = data[i].close * k + ema * (1 - k);
    result.push({ time: data[i].time, value: ema });
  }
  
  return result;
}

/**
 * Calculate Relative Strength Index (RSI)
 * @param {Array} data - Array of {time, close} objects
 * @param {number} period - RSI period (default: 14)
 * @returns {Array} Array of {time, value} for RSI line (0-100)
 */
export function calculateRSI(data, period = 14) {
  if (!data || data.length < period + 1) return [];
  
  const result = [];
  let gains = 0;
  let losses = 0;
  
  // Calculate initial average gain/loss
  for (let i = 1; i <= period; i++) {
    const change = data[i].close - data[i - 1].close;
    if (change > 0) {
      gains += change;
    } else {
      losses -= change;
    }
  }
  
  let avgGain = gains / period;
  let avgLoss = losses / period;
  let rs = avgGain / avgLoss;
  let rsi = 100 - (100 / (1 + rs));
  
  result.push({ time: data[period].time, value: rsi });
  
  // Calculate RSI for remaining values (smoothed)
  for (let i = period + 1; i < data.length; i++) {
    const change = data[i].close - data[i - 1].close;
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    
    rs = avgGain / avgLoss;
    rsi = 100 - (100 / (1 + rs));
    
    result.push({ time: data[i].time, value: rsi });
  }
  
  return result;
}

/**
 * Calculate MACD (Moving Average Convergence Divergence)
 * @param {Array} data - Array of {time, close} objects
 * @param {number} fastPeriod - Fast EMA period (default: 12)
 * @param {number} slowPeriod - Slow EMA period (default: 26)
 * @param {number} signalPeriod - Signal line EMA period (default: 9)
 * @returns {Object} {macd: Array, signal: Array, histogram: Array}
 */
export function calculateMACD(data, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
  if (!data || data.length < slowPeriod + signalPeriod) {
    return { macd: [], signal: [], histogram: [] };
  }
  
  const fastEMA = calculateEMA(data, fastPeriod);
  const slowEMA = calculateEMA(data, slowPeriod);
  
  // Calculate MACD line (fast EMA - slow EMA)
  const macdLine = [];
  const startIndex = slowPeriod - 1;
  
  for (let i = 0; i < slowEMA.length; i++) {
    const fastIndex = i + (fastPeriod - slowPeriod);
    if (fastIndex >= 0 && fastIndex < fastEMA.length && fastEMA[fastIndex] && slowEMA[i]) {
      const fastValue = fastEMA[fastIndex].value;
      const slowValue = slowEMA[i].value;
      if (Number.isFinite(fastValue) && Number.isFinite(slowValue)) {
        const macdValue = fastValue - slowValue;
        macdLine.push({
          time: slowEMA[i].time,
          value: macdValue
        });
      }
    }
  }
  
  if (macdLine.length === 0) {
    return { macd: [], signal: [], histogram: [] };
  }
  
  // Calculate signal line (EMA of MACD)
  const signalLine = calculateEMA(macdLine, signalPeriod);
  
  if (signalLine.length === 0) {
    return { macd: macdLine, signal: [], histogram: [] };
  }
  
  // Calculate histogram (MACD - Signal)
  const histogram = [];
  for (let i = 0; i < signalLine.length; i++) {
    const macdIndex = i + (macdLine.length - signalLine.length);
    if (macdIndex >= 0 && macdIndex < macdLine.length && macdLine[macdIndex] && signalLine[i]) {
      const macdValue = macdLine[macdIndex].value;
      const signalValue = signalLine[i].value;
      if (Number.isFinite(macdValue) && Number.isFinite(signalValue)) {
        histogram.push({
          time: signalLine[i].time,
          value: macdValue - signalValue,
          color: macdValue - signalValue >= 0 ? '#26a69a' : '#ef5350'
        });
      }
    }
  }
  
  return {
    macd: macdLine,
    signal: signalLine,
    histogram: histogram
  };
}

/**
 * Calculate Bollinger Bands
 * @param {Array} data - Array of {time, close} objects
 * @param {number} period - MA period (default: 20)
 * @param {number} stdDev - Standard deviation multiplier (default: 2)
 * @returns {Object} {upper: Array, middle: Array, lower: Array}
 */
export function calculateBollingerBands(data, period = 20, stdDev = 2) {
  if (!data || data.length < period) {
    return { upper: [], middle: [], lower: [] };
  }
  
  const middle = calculateSMA(data, period);
  const upper = [];
  const lower = [];
  
  for (let i = period - 1; i < data.length; i++) {
    // Calculate standard deviation
    let sum = 0;
    for (let j = 0; j < period; j++) {
      const diff = data[i - j].close - middle[i - period + 1].value;
      sum += diff * diff;
    }
    const std = Math.sqrt(sum / period);
    
    const time = data[i].time;
    const midValue = middle[i - period + 1].value;
    
    upper.push({ time, value: midValue + (stdDev * std) });
    lower.push({ time, value: midValue - (stdDev * std) });
  }
  
  return { upper, middle, lower };
}

/**
 * Calculate Stochastic Oscillator
 * @param {Array} data - Array of {time, high, low, close} objects
 * @param {number} kPeriod - %K period (default: 14)
 * @param {number} dPeriod - %D period (default: 3)
 * @returns {Object} {k: Array, d: Array}
 */
export function calculateStochastic(data, kPeriod = 14, dPeriod = 3) {
  if (!data || data.length < kPeriod + dPeriod) {
    return { k: [], d: [] };
  }
  
  const kLine = [];
  
  // Calculate %K
  for (let i = kPeriod - 1; i < data.length; i++) {
    let highest = data[i].high;
    let lowest = data[i].low;
    
    for (let j = 0; j < kPeriod; j++) {
      highest = Math.max(highest, data[i - j].high);
      lowest = Math.min(lowest, data[i - j].low);
    }
    
    const k = ((data[i].close - lowest) / (highest - lowest)) * 100;
    kLine.push({ time: data[i].time, value: k, close: data[i].close });
  }
  
  // Calculate %D (SMA of %K)
  const dLine = calculateSMA(kLine, dPeriod);
  
  return {
    k: kLine.map(item => ({ time: item.time, value: item.value })),
    d: dLine
  };
}

/**
 * Calculate Average True Range (ATR)
 * @param {Array} data - Array of {time, high, low, close} objects
 * @param {number} period - ATR period (default: 14)
 * @returns {Array} Array of {time, value} for ATR line
 */
export function calculateATR(data, period = 14) {
  if (!data || data.length < period + 1) return [];
  
  const trueRanges = [];
  
  // Calculate True Range for each candle
  for (let i = 1; i < data.length; i++) {
    const high = data[i].high;
    const low = data[i].low;
    const prevClose = data[i - 1].close;
    
    const tr = Math.max(
      high - low,
      Math.abs(high - prevClose),
      Math.abs(low - prevClose)
    );
    
    trueRanges.push({ time: data[i].time, value: tr });
  }
  
  // Calculate ATR (smoothed average of TR)
  const atr = [];
  let sum = 0;
  
  // Initial ATR (simple average)
  for (let i = 0; i < period; i++) {
    sum += trueRanges[i].value;
  }
  let atrValue = sum / period;
  atr.push({ time: trueRanges[period - 1].time, value: atrValue });
  
  // Smoothed ATR
  for (let i = period; i < trueRanges.length; i++) {
    atrValue = ((atrValue * (period - 1)) + trueRanges[i].value) / period;
    atr.push({ time: trueRanges[i].time, value: atrValue });
  }
  
  return atr;
}

/**
 * Calculate Fibonacci Retracement Levels
 * @param {number} high - Highest price in range
 * @param {number} low - Lowest price in range
 * @returns {Object} Fibonacci levels
 */
export function calculateFibonacci(high, low) {
  const diff = high - low;
  
  return {
    level_0: high,
    level_236: high - (diff * 0.236),
    level_382: high - (diff * 0.382),
    level_500: high - (diff * 0.500),
    level_618: high - (diff * 0.618),
    level_786: high - (diff * 0.786),
    level_100: low
  };
}
