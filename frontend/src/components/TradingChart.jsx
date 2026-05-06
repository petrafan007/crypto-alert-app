import React, { useEffect, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import axios from 'axios';
import {
  calculateSMA,
  calculateRSI,
  calculateMACD,
  calculateBollingerBands,
  calculateStochastic,
  calculateATR
} from '../utils/technicalIndicators';
import './TradingChart.css';

const TradingChart = ({ symbol, onSymbolChange, tradingPairs = [] }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candlestickSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const [chartReady, setChartReady] = useState(false);
  
  // Indicator series refs
  const ma7Ref = useRef(null);
  const ma25Ref = useRef(null);
  const ma99Ref = useRef(null);
  const bbUpperRef = useRef(null);
  const bbMiddleRef = useRef(null);
  const bbLowerRef = useRef(null);
  const buyMarkersRef = useRef([]);
  const sellMarkersRef = useRef([]);
  
  // Separate chart for RSI, MACD, Stochastic, ATR
  const indicatorContainerRef = useRef(null);
  const indicatorChartRef = useRef(null);
  const rsiSeriesRef = useRef(null);
  const macdSeriesRef = useRef(null);
  const macdSignalRef = useRef(null);
  const macdHistogramRef = useRef(null);
  const stochKRef = useRef(null);
  const stochDRef = useRef(null);
  const atrSeriesRef = useRef(null);
  const markerTooltipRef = useRef(null);
  const markerDataRef = useRef({});
  const crosshairMoveHandlerRef = useRef(null);
  const indicatorSyncHandlerRef = useRef(null);
  const resizeHandlerRef = useRef(null);
  
  // State
  const [interval, setInterval] = useState('1d');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [klines, setKlines] = useState([]);
  const [transactions, setTransactions] = useState([]);
  
  // Indicator toggles
  const [indicators, setIndicators] = useState({
    ma7: false,
    ma25: true,
    ma99: false,
    rsi: false,
    macd: false,
    bb: false,
    stoch: false,
    atr: false,
    volume: true,
    fibonacci: false
  });
  
  const baseAsset = symbol.replace('USDT', '').replace('USD', '');

  const formatAmount = (value) => {
    if (value === null || value === undefined) return '0';
    const absValue = Math.abs(Number(value));
    const digits = absValue >= 1 ? 4 : 8;
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits
    });
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '$0.00';
  
    return Number(value).toLocaleString(undefined, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  };

  const formatDateTime = (epochSeconds) => {
    if (!epochSeconds) return '';
    return new Date(epochSeconds * 1000).toLocaleString();
  };

  const intervalToSeconds = (selectedInterval) => {
    switch (selectedInterval) {
      case '1m':
        return 60;
      case '5m':
        return 60 * 5;
      case '15m':
        return 60 * 15;
      case '30m':
        return 60 * 30;
      case '1h':
        return 60 * 60;
      case '4h':
        return 60 * 60 * 4;
      case '1d':
        return 60 * 60 * 24;
      case '1w':
        return 60 * 60 * 24 * 7;
      case '1M':
        return 60 * 60 * 24 * 30;
      default:
        return 60 * 60 * 24;
    }
  };
  // Fetch initial klines and transactions, then use WebSocket for updates
  useEffect(() => {
    if (!symbol) return;
    
    let ws = null;
    
    const fetchInitialData = async () => {
      setLoading(true);
      setError(null);
      
      try {
        // Fetch initial klines ONCE
        const klinesRes = await axios.get(`/api/trading/klines/${symbol}`, {
          params: { interval, limit: 1000 },
          withCredentials: true
        });
        
        if (klinesRes.data.success) {
          const normalized = klinesRes.data.klines
            .map(k => ({
              time: typeof k.time === 'string' ? Math.floor(new Date(k.time).getTime() / 1000) : Math.round(Number(k.time)),
              open: Number(k.open),
              high: Number(k.high),
              low: Number(k.low),
              close: Number(k.close),
              volume: Number(k.volume ?? 0)
            }))
            .filter(k => Number.isFinite(k.time) && Number.isFinite(k.open) && Number.isFinite(k.high) && Number.isFinite(k.low) && Number.isFinite(k.close))
            .sort((a, b) => a.time - b.time);

          setKlines(normalized);
        }
        
        // Fetch transactions (optional)
        try {
          const transRes = await axios.get(`/api/trading/transactions/${symbol}`, {
            withCredentials: true
          });
          
          if (transRes.data.success) {
            setTransactions(transRes.data.transactions);
          }
        } catch (transErr) {
          console.warn('Failed to fetch transactions (chart will still render):', transErr);
          setTransactions([]);
        }
        
        setLoading(false);
        
        // NOW establish WebSocket for live updates
        const stream = `${symbol.toLowerCase()}@kline_${interval}`;
        ws = new WebSocket(`wss://stream.binance.us:9443/ws/${stream}`);
        
        ws.onopen = () => {
          console.log('WebSocket connected for', symbol, interval);
        };
        
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.e === 'kline' && data.k) {
              const kline = data.k;
              const newCandle = {
                time: Math.floor(kline.t / 1000),
                open: Number(kline.o),
                high: Number(kline.h),
                low: Number(kline.l),
                close: Number(kline.c),
                volume: Number(kline.v)
              };
              
              setKlines(prev => {
                const lastCandle = prev[prev.length - 1];
                if (!lastCandle || newCandle.time > lastCandle.time) {
                  // New candle
                  return [...prev.slice(-999), newCandle];
                } else if (newCandle.time === lastCandle.time) {
                  // Update current candle
                  return [...prev.slice(0, -1), newCandle];
                }
                return prev;
              });
            }
          } catch (err) {
            console.error('WebSocket message error:', err);
          }
        };
        
        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
        };
        
        ws.onclose = () => {
          console.log('WebSocket disconnected for', symbol);
        };
        
      } catch (err) {
        console.error('Chart data fetch error:', err);
        setError(err.response?.data?.error || 'Failed to load chart data');
        setLoading(false);
      }
    };
    
    fetchInitialData();
    
    // Cleanup WebSocket on unmount or symbol/interval change
    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [symbol, interval]);
  

  // Initialize chart ONCE
  useEffect(() => {
    if (!chartReady || !chartContainerRef.current || klines.length === 0) {
      console.log('Chart init prerequisites not met:', { 
        chartReady, 
        hasRef: !!chartContainerRef.current,
        klinesLength: klines.length 
      });
      return;
    }
    
    if (chartRef.current) {
      console.log('Chart already initialized');
      return;
    }
    
    const container = chartContainerRef.current;
    if (!container) {
      return;
    }

    const containerStyles = window.getComputedStyle(container);
    const paddingLeft = parseFloat(containerStyles.paddingLeft || '0');
    const paddingRight = parseFloat(containerStyles.paddingRight || '0');
    const rawWidth = container.clientWidth;
    const containerWidth = rawWidth - paddingLeft - paddingRight;
    const containerHeight = container.clientHeight || container.offsetHeight || 600;
    const chartWidth = Math.max(containerWidth, 320);

    console.log('Attempting chart creation:', { rawWidth, containerWidth, containerHeight });
    
    if (chartWidth <= 0 || containerHeight === 0) {
      console.log('Container has no dimensions, retrying...');
      return;
    }
    
    try {
        console.log('Creating chart NOW with dimensions:', chartWidth, 'x', containerHeight);
        
        // Create main chart with improved dark mode styling
        chartRef.current = createChart(container, {
          width: chartWidth,
          height: containerHeight,
          layout: {
            background: { color: '#0a0e27' },
            textColor: '#d1d5db',
          },
          watermark: {
            visible: false,
          },
          grid: {
            vertLines: { 
              color: 'rgba(102, 126, 234, 0.6)',
              style: 0,
              visible: true,
            },
            horzLines: { 
              color: 'rgba(102, 126, 234, 0.6)',
              style: 0,
              visible: true,
            },
          },
          crosshair: {
            mode: 1,
            vertLine: {
              color: '#667eea',
              width: 1,
              style: 3,
              labelBackgroundColor: '#667eea',
            },
            horzLine: {
              color: '#667eea',
              width: 1,
              style: 3,
              labelBackgroundColor: '#667eea',
            },
          },
          leftPriceScale: {
            visible: false,
            borderVisible: false,
            entireTextOnly: true,
          },
          rightPriceScale: {
            borderColor: '#2a2e39',
            scaleMargins: {
              top: 0.05,
              bottom: 0.05,
            },
            autoScale: true,
            entireTextOnly: true,
            borderVisible: false,
            ticksVisible: true,
            alignLabels: true,
            minimumWidth: 100,
          },
          timeScale: {
            borderColor: '#2a2e39',
            timeVisible: true,
            secondsVisible: false,
            fixLeftEdge: false,
            fixRightEdge: false,
            borderVisible: true,
            rightOffset: 6,
            barSpacing: 7,
            minBarSpacing: 3,
          },
          handleScroll: {
            vertTouchDrag: true,
          },
          handleScale: {
            axisPressedMouseMove: true,
          },
        });
        // Add candlestick series with improved colors
      candlestickSeriesRef.current = chartRef.current.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderUpColor: '#26a69a',
        borderDownColor: '#ef5350',
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
        visible: true,
      });
      
      // Add volume series with better styling
      volumeSeriesRef.current = chartRef.current.addHistogramSeries({
        color: '#667eea',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: 'volume',
        lastValueVisible: false,
        priceLineVisible: false,
        baseLineVisible: false,
      });

      chartRef.current.priceScale('volume').applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
        visible: false,
        borderVisible: false,
        drawTicks: false,
        entireTextOnly: true,
      });

      chartRef.current.priceScale('right').applyOptions({
        borderVisible: false,
        drawTicks: true,
        entireTextOnly: true,
        alignLabels: true,
        minimumWidth: 100,
        scaleMargins: {
          top: 0.05,
          bottom: 0.05,
        },
      });

      chartRef.current.priceScale('left').applyOptions({
        visible: false,
        borderVisible: false,
      });
      
      const tooltipEl = document.createElement('div');
      tooltipEl.className = 'chart-marker-tooltip';
      tooltipEl.style.display = 'none';
      container.appendChild(tooltipEl);
      markerTooltipRef.current = tooltipEl;

      const handleCrosshairMove = (param) => {
        const tooltip = markerTooltipRef.current;
        if (!tooltip) {
          return;
        }
        const point = param?.point;
        const rawTime = param?.time;
        if (!point || point.x < 0 || point.y < 0 || rawTime === undefined) {
          tooltip.style.display = 'none';
          return;
        }
        const normalizedTime = typeof rawTime === 'number'
          ? rawTime
          : rawTime?.timestamp ?? null;
        if (!normalizedTime) {
          tooltip.style.display = 'none';
          return;
        }

        const markerEntries = markerDataRef.current[normalizedTime];
        if (!markerEntries || markerEntries.length === 0) {
          tooltip.style.display = 'none';
          return;
        }

        // Group by type and calculate totals
        const buyTransactions = markerEntries.filter(m => m.type === 'BUY');
        const sellTransactions = markerEntries.filter(m => m.type === 'SELL');
        
        let tooltipContent = '';
        
        if (buyTransactions.length > 0) {
          const totalBuyAmount = buyTransactions.reduce((sum, tx) => sum + (tx.amount || 0), 0);
          const totalBuyValue = buyTransactions.reduce((sum, tx) => sum + (tx.amount * tx.price || 0), 0);
          tooltipContent += `
            <div class="marker-tooltip-heading">Buy ${baseAsset}</div>
            <div class="marker-tooltip-line">Transactions: <span>${buyTransactions.length}</span></div>
            <div class="marker-tooltip-line">Total Amount: <span>${formatAmount(totalBuyAmount)}</span></div>
            <div class="marker-tooltip-line">Total Value: <span>${formatCurrency(totalBuyValue)}</span></div>
          `;
        }
        
        if (sellTransactions.length > 0) {
          if (tooltipContent) tooltipContent += '<div style="margin-top: 8px;"></div>';
          const totalSellAmount = sellTransactions.reduce((sum, tx) => sum + (tx.amount || 0), 0);
          const totalSellValue = sellTransactions.reduce((sum, tx) => sum + (tx.amount * tx.price || 0), 0);
          tooltipContent += `
            <div class="marker-tooltip-heading">Sell ${baseAsset}</div>
            <div class="marker-tooltip-line">Transactions: <span>${sellTransactions.length}</span></div>
            <div class="marker-tooltip-line">Total Amount: <span>${formatAmount(totalSellAmount)}</span></div>
            <div class="marker-tooltip-line">Total Value: <span>${formatCurrency(totalSellValue)}</span></div>
          `;
        }
        
        const firstEntry = markerEntries[0];
        tooltipContent += `<div class="marker-tooltip-line" style="margin-top: 4px;">${formatDateTime(firstEntry.originalTime)}</div>`;

        tooltip.innerHTML = tooltipContent;
        tooltip.style.display = 'flex';

        const containerBounds = container.getBoundingClientRect();

        const tooltipRect = tooltip.getBoundingClientRect();
        let left = point.x + 16;
        let top = point.y + 16;

        if (left + tooltipRect.width > containerBounds.width) {
          left = point.x - tooltipRect.width - 16;
        }
        if (left < 0) {
          left = 0;
        }
        if (top + tooltipRect.height > containerBounds.height) {
          top = point.y - tooltipRect.height - 16;
        }
        if (top < 0) {
          top = 0;
        }

        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      };

      chartRef.current.subscribeCrosshairMove(handleCrosshairMove);
      crosshairMoveHandlerRef.current = handleCrosshairMove;

      const MAX_RENDER_CANDLES = 360;
      if (klines.length > 0 && candlestickSeriesRef.current) {
        const initialSlice = klines.slice(-MAX_RENDER_CANDLES);
        const initialCandleData = initialSlice.map(({ time, open, high, low, close }) => ({
          time,
          open,
          high,
          low,
          close,
        }));
        candlestickSeriesRef.current.setData(initialCandleData);

        if (indicators.volume && volumeSeriesRef.current) {
          const initialVolumeData = initialSlice.map(k => ({
            time: k.time,
            value: Number.isFinite(k.volume) ? k.volume : 0,
            color: k.close >= k.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
          }));
          volumeSeriesRef.current.setData(initialVolumeData);
        }

        chartRef.current.timeScale().fitContent();
        chartRef.current.timeScale().applyOptions({
          rightOffset: 12,
          barSpacing: 12,
          minBarSpacing: 6,
        });
      }

      // Handle resize so the chart always fills its container
      const handleResize = () => {
        if (chartRef.current && chartContainerRef.current) {
          const containerEl = chartContainerRef.current;
          const styles = window.getComputedStyle(containerEl);
          const paddingLeftPx = parseFloat(styles.paddingLeft || '0');
          const paddingRightPx = parseFloat(styles.paddingRight || '0');
          const nextWidth = containerEl.clientWidth - paddingLeftPx - paddingRightPx;
          const nextHeight = containerEl.clientHeight || containerEl.offsetHeight || containerHeight;
          chartRef.current.resize(Math.max(nextWidth, 320), nextHeight);
        }
        if (indicatorChartRef.current && indicatorContainerRef.current) {
          const indEl = indicatorContainerRef.current;
          const indStyles = window.getComputedStyle(indEl);
          const indPaddingLeft = parseFloat(indStyles.paddingLeft || '0');
          const indPaddingRight = parseFloat(indStyles.paddingRight || '0');
          const indicatorWidth = indEl.clientWidth - indPaddingLeft - indPaddingRight;
          const indicatorHeight = indEl.clientHeight || 200;
          indicatorChartRef.current.resize(Math.max(indicatorWidth, 320), indicatorHeight);
        }
      };

      window.addEventListener('resize', handleResize);
      resizeHandlerRef.current = handleResize;
      handleResize();
      
      console.log('Chart initialized successfully!');
      
      // Set initial data
      candlestickSeriesRef.current.setData(klines);
      
      // Set volume data if enabled
      if (indicators.volume && volumeSeriesRef.current) {
        const volumeData = klines.map(k => ({
          time: k.time,
          value: k.volume,
          color: k.close >= k.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
        }));
        volumeSeriesRef.current.setData(volumeData);
      }
      
      // Fit content
      chartRef.current.timeScale().fitContent();
      
    } catch (error) {
      console.error('Failed to create chart:', error);
    }
  }, [chartReady, klines.length]);

  useEffect(() => {
    const hasOverlayIndicators = indicators.rsi || indicators.macd || indicators.stoch || indicators.atr;

    if (!hasOverlayIndicators) {
      if (indicatorSyncHandlerRef.current && chartRef.current) {
        chartRef.current.timeScale().unsubscribeVisibleLogicalRangeChange(indicatorSyncHandlerRef.current);
        indicatorSyncHandlerRef.current = null;
      }
      if (indicatorChartRef.current) {
        indicatorChartRef.current.remove();
        indicatorChartRef.current = null;
        if (indicatorContainerRef.current) {
          indicatorContainerRef.current.innerHTML = '';
        }
      }
      rsiSeriesRef.current = null;
      macdSeriesRef.current = null;
      macdSignalRef.current = null;
      macdHistogramRef.current = null;
      stochKRef.current = null;
      stochDRef.current = null;
      atrSeriesRef.current = null;
      return;
    }

    if (!indicatorContainerRef.current || !chartRef.current) {
      return;
    }

  if (!indicatorChartRef.current) {
      const indicatorEl = indicatorContainerRef.current;
      const indStyles = window.getComputedStyle(indicatorEl);
      const indPaddingLeft = parseFloat(indStyles.paddingLeft || '0');
      const indPaddingRight = parseFloat(indStyles.paddingRight || '0');
      const rawIndicatorWidth = indicatorEl.clientWidth;
      const effectiveIndicatorWidth = Math.max(rawIndicatorWidth - indPaddingLeft - indPaddingRight, 320);
      const indicatorHeight = indicatorEl.clientHeight || 200;

      console.log('Creating indicator chart with dimensions:', effectiveIndicatorWidth, 'x', indicatorHeight);

      indicatorChartRef.current = createChart(indicatorEl, {
        width: effectiveIndicatorWidth,
        height: indicatorHeight,
        layout: {
          background: { color: '#0a0e27' },
          textColor: '#d1d5db',
        },
        grid: {
          vertLines: { 
            color: 'rgba(102, 126, 234, 0.6)',
            style: 0,
            visible: true,
          },
          horzLines: { 
            color: 'rgba(102, 126, 234, 0.6)',
            style: 0,
            visible: true,
          },
        },
        leftPriceScale: {
          visible: false,
          borderVisible: false,
        },
        rightPriceScale: {
          borderColor: '#2a2e39',
          scaleMargins: {
            top: 0.1,
            bottom: 0.1,
          },
          borderVisible: false,
          drawTicks: true,
          minimumWidth: 100,
        },
        watermark: {
          visible: false,
        },
        timeScale: {
          borderColor: '#2a2e39',
          visible: false,
          fixLeftEdge: false,
        },
        crosshair: {
          mode: 0,
        },
        handleScroll: false,
        handleScale: false,
      });

      const syncHandler = (timeRange) => {
        if (!timeRange || !indicatorChartRef.current) return;
        indicatorChartRef.current.timeScale().setVisibleLogicalRange(timeRange);
      };
      chartRef.current.timeScale().subscribeVisibleLogicalRangeChange(syncHandler);
      indicatorSyncHandlerRef.current = syncHandler;
    }
  }, [indicators.rsi, indicators.macd, indicators.stoch, indicators.atr, chartReady]);
  
  // Update chart data when klines change
  useEffect(() => {
    if (!chartRef.current || !candlestickSeriesRef.current || klines.length === 0) {
      return;
    }
    
    console.log('Updating chart data with', klines.length, 'candles');
    
    if (klines.length === 0) {
      console.warn('Klines array is empty when attempting to render chart');
      return;
    }

    console.log('First candle sample:', klines[0], 'Last candle sample:', klines[klines.length - 1]);
    console.table(klines.slice(0, 5));

    const MAX_RENDER_CANDLES = 360;
    const renderSlice = klines.slice(-MAX_RENDER_CANDLES);

    const candlestickData = renderSlice.map(({ time, open, high, low, close }) => ({
      time,
      open,
      high,
      low,
      close,
    }));

    // Update candlestick data with explicit candle objects
    candlestickSeriesRef.current.setData(candlestickData);
    
    // Update volume data
    if (volumeSeriesRef.current) {
      if (indicators.volume) {
        const volumeData = renderSlice.map(k => ({
          time: k.time,
          value: Number.isFinite(k.volume) ? k.volume : 0,
          color: k.close >= k.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
        }));
        volumeSeriesRef.current.setData(volumeData);
        volumeSeriesRef.current.applyOptions({ visible: true });
        chartRef.current.priceScale('volume').applyOptions({ visible: true });
      } else {
        volumeSeriesRef.current.setData([]);
        volumeSeriesRef.current.applyOptions({ visible: false });
        chartRef.current.priceScale('volume').applyOptions({ visible: false });
      }
    }
    
    // Fit content to show all data without leaving blank gutters
    chartRef.current.timeScale().fitContent();
    chartRef.current.timeScale().applyOptions({
      rightOffset: 12,
      barSpacing: 12,
      minBarSpacing: 6,
    });
  }, [klines, indicators.volume]);
  
  // Update indicators when toggled
  useEffect(() => {
    if (!chartRef.current || klines.length === 0) return;
    
    // MA 7
    if (indicators.ma7) {
      if (!ma7Ref.current) {
        ma7Ref.current = chartRef.current.addLineSeries({
          color: '#2196F3',
          lineWidth: 1,
          title: 'MA 7'
        });
      }
      ma7Ref.current.setData(calculateSMA(klines, 7));
    } else if (ma7Ref.current) {
      chartRef.current.removeSeries(ma7Ref.current);
      ma7Ref.current = null;
    }
    
    // MA 25
    if (indicators.ma25) {
      if (!ma25Ref.current) {
        ma25Ref.current = chartRef.current.addLineSeries({
          color: '#FF9800',
          lineWidth: 2,
          title: 'MA 25'
        });
      }
      ma25Ref.current.setData(calculateSMA(klines, 25));
    } else if (ma25Ref.current) {
      chartRef.current.removeSeries(ma25Ref.current);
      ma25Ref.current = null;
    }
    
    // MA 99
    if (indicators.ma99) {
      if (!ma99Ref.current) {
        ma99Ref.current = chartRef.current.addLineSeries({
          color: '#E91E63',
          lineWidth: 2,
          title: 'MA 99'
        });
      }
      ma99Ref.current.setData(calculateSMA(klines, 99));
    } else if (ma99Ref.current) {
      chartRef.current.removeSeries(ma99Ref.current);
      ma99Ref.current = null;
    }
    
    // Bollinger Bands
    if (indicators.bb) {
      const bb = calculateBollingerBands(klines, 20, 2);
      
      if (!bbUpperRef.current) {
        bbUpperRef.current = chartRef.current.addLineSeries({
          color: '#9C27B0',
          lineWidth: 1,
          lineStyle: 2,
          title: 'BB Upper'
        });
      }
      if (!bbMiddleRef.current) {
        bbMiddleRef.current = chartRef.current.addLineSeries({
          color: '#9C27B0',
          lineWidth: 1,
          title: 'BB Middle'
        });
      }
      if (!bbLowerRef.current) {
        bbLowerRef.current = chartRef.current.addLineSeries({
          color: '#9C27B0',
          lineWidth: 1,
          lineStyle: 2,
          title: 'BB Lower'
        });
      }
      bbUpperRef.current.setData(bb.upper);
      bbMiddleRef.current.setData(bb.middle);
      bbLowerRef.current.setData(bb.lower);
      
    } else {
      if (bbUpperRef.current) {
        chartRef.current.removeSeries(bbUpperRef.current);
        bbUpperRef.current = null;
      }
      if (bbMiddleRef.current) {
        chartRef.current.removeSeries(bbMiddleRef.current);
        bbMiddleRef.current = null;
      }
      if (bbLowerRef.current) {
        chartRef.current.removeSeries(bbLowerRef.current);
        bbLowerRef.current = null;
      }
    }
    
  }, [klines, indicators.ma7, indicators.ma25, indicators.ma99, indicators.bb]);
  
  // Update RSI
  useEffect(() => {
    if (!indicatorChartRef.current || klines.length === 0) return;
    
    if (indicators.rsi) {
      if (!rsiSeriesRef.current) {
        rsiSeriesRef.current = indicatorChartRef.current.addLineSeries({
          color: '#2196F3',
          lineWidth: 2,
          title: '', // NO TITLE to prevent legend
          priceScaleId: 'right',
          autoscaleInfoProvider: () => ({
            priceRange: {
              minValue: 0,
              maxValue: 100,
            },
          }),
        });
      }
      const rsiData = calculateRSI(klines, 14);
      console.log('Setting RSI data:', rsiData.length, 'points', 'First:', rsiData[0], 'Last:', rsiData[rsiData.length-1]);
      console.log('Sample RSI values:', rsiData.slice(0, 5));
      console.log('RSI value range:', Math.min(...rsiData.map(d => d.value)), 'to', Math.max(...rsiData.map(d => d.value)));
      rsiSeriesRef.current.setData(rsiData);
      
      // Force resize the indicator chart to match container
      if (indicatorContainerRef.current) {
        const width = indicatorContainerRef.current.clientWidth;
        const height = indicatorContainerRef.current.clientHeight || 200;
        console.log('Resizing indicator chart to:', width, 'x', height);
        indicatorChartRef.current.resize(width, height);
      }
      
      // Force the chart to fit content
      indicatorChartRef.current.timeScale().fitContent();
      
      // Also fit the price scale
      indicatorChartRef.current.priceScale('right').applyOptions({
        autoScale: true,
      });
      
      // Check if indicator chart canvas is visible
      if (indicatorContainerRef.current) {
        const canvas = indicatorContainerRef.current.querySelector('canvas');
        if (canvas) {
          console.log('Indicator canvas found:', canvas.width, 'x', canvas.height, 'visible:', window.getComputedStyle(canvas).display);
          const ctx = canvas.getContext('2d');
          const imageData = ctx.getImageData(0, 0, Math.min(100, canvas.width), Math.min(100, canvas.height));
          const hasContent = imageData.data.some(pixel => pixel !== 0);
          console.log('Canvas has drawn content:', hasContent);
        } else {
          console.log('NO CANVAS FOUND in indicator container!');
        }
      }
    } else if (rsiSeriesRef.current) {
      indicatorChartRef.current.removeSeries(rsiSeriesRef.current);
      rsiSeriesRef.current = null;
    }
  }, [klines, indicators.rsi]);
  
  // Update MACD
  useEffect(() => {
    if (!indicatorChartRef.current || klines.length === 0) return;
    
    if (indicators.macd) {
      const macd = calculateMACD(klines);
      
      if (!macdSeriesRef.current) {
        macdSeriesRef.current = indicatorChartRef.current.addLineSeries({
          color: '#2196F3',
          lineWidth: 2,
          title: '' // NO TITLE
        });
      }
      if (!macdSignalRef.current) {
        macdSignalRef.current = indicatorChartRef.current.addLineSeries({
          color: '#FF9800',
          lineWidth: 2,
          title: '' // NO TITLE
        });
      }
      if (!macdHistogramRef.current) {
        macdHistogramRef.current = indicatorChartRef.current.addHistogramSeries({
          title: '' // NO TITLE
        });
      }
      
      macdSeriesRef.current.setData(macd.macd);
      macdSignalRef.current.setData(macd.signal);
      macdHistogramRef.current.setData(macd.histogram);
    } else {
      if (macdSeriesRef.current) {
        indicatorChartRef.current.removeSeries(macdSeriesRef.current);
        macdSeriesRef.current = null;
      }
      if (macdSignalRef.current) {
        indicatorChartRef.current.removeSeries(macdSignalRef.current);
        macdSignalRef.current = null;
      }
      if (macdHistogramRef.current) {
        indicatorChartRef.current.removeSeries(macdHistogramRef.current);
        macdHistogramRef.current = null;
      }
    }
  }, [klines, indicators.macd]);
  
  // Update Stochastic
  useEffect(() => {
    if (!indicatorChartRef.current || klines.length === 0) return;
    
    if (indicators.stoch) {
      const stoch = calculateStochastic(klines);
      
      if (!stochKRef.current) {
        stochKRef.current = indicatorChartRef.current.addLineSeries({
          color: '#2196F3',
          lineWidth: 2,
          title: '%K'
        });
      }
      if (!stochDRef.current) {
        stochDRef.current = indicatorChartRef.current.addLineSeries({
          color: '#FF9800',
          lineWidth: 2,
          title: '%D'
        });
      }
      
      stochKRef.current.setData(stoch.k);
      stochDRef.current.setData(stoch.d);
    } else {
      if (stochKRef.current) {
        indicatorChartRef.current.removeSeries(stochKRef.current);
        stochKRef.current = null;
      }
      if (stochDRef.current) {
        indicatorChartRef.current.removeSeries(stochDRef.current);
        stochDRef.current = null;
      }
    }
  }, [klines, indicators.stoch]);
  
  // Update ATR
  useEffect(() => {
    if (!indicatorChartRef.current || klines.length === 0) return;
    
    if (indicators.atr) {
      if (!atrSeriesRef.current) {
        atrSeriesRef.current = indicatorChartRef.current.addLineSeries({
          color: '#E91E63',
          lineWidth: 2,
          title: 'ATR (14)'
        });
      }
      atrSeriesRef.current.setData(calculateATR(klines, 14));
    } else if (atrSeriesRef.current) {
      indicatorChartRef.current.removeSeries(atrSeriesRef.current);
      atrSeriesRef.current = null;
    }
  }, [klines, indicators.atr]);
  
  // Add buy/sell markers
  useEffect(() => {
    if (!candlestickSeriesRef.current) {
      return;
    }

    if (!transactions || transactions.length === 0 || klines.length === 0) {
      candlestickSeriesRef.current.setMarkers([]);
      markerDataRef.current = {};
      if (markerTooltipRef.current) {
        markerTooltipRef.current.style.display = 'none';
      }
      return;
    }

    const bucketSize = intervalToSeconds(interval);
    const candleTimes = klines.map(k => k.time);
    const candleTimeSet = new Set(candleTimes);
    const findClosestTime = (target) => {
      if (!bucketSize) return target;
      const snapped = Math.floor(target / bucketSize) * bucketSize;
      if (candleTimeSet.has(snapped)) {
        return snapped;
      }
      if (candleTimeSet.has(snapped + bucketSize)) {
        return snapped + bucketSize;
      }
      if (candleTimes.length === 0) {
        return target;
      }
      let closest = candleTimes[0];
      let minDiff = Math.abs(target - closest);
      for (let i = 1; i < candleTimes.length; i += 1) {
        const diff = Math.abs(target - candleTimes[i]);
        if (diff < minDiff) {
          closest = candleTimes[i];
          minDiff = diff;
        }
      }
      return closest;
    };

    const markerData = {};
    const markersByTime = new Map(); // Track markers by time and type
    
    // Group transactions by time and type
    transactions.forEach((tx, index) => {
      const mappedTime = findClosestTime(tx.time);
      const key = `${mappedTime}-${tx.type}`;
      
      if (!markersByTime.has(key)) {
        markersByTime.set(key, {
          type: tx.type,
          mappedTime,
          transactions: []
        });
      }
      markersByTime.get(key).transactions.push(tx);
      
      if (!markerData[mappedTime]) {
        markerData[mappedTime] = [];
      }
      markerData[mappedTime].push({
        ...tx,
        originalTime: tx.time,
        mappedTime,
      });
    });
    
    // Create consolidated markers (max 2 per candle: 1 BUY, 1 SELL)
    const markers = Array.from(markersByTime.values()).map(({ type, mappedTime, transactions }) => {
      return {
        id: `${type}-${mappedTime}`,
        time: mappedTime,
        position: type === 'BUY' ? 'belowBar' : 'aboveBar',
        color: type === 'BUY' ? '#22c55e' : '#ef4444',
        shape: type === 'BUY' ? 'arrowUp' : 'arrowDown',
        // NO TEXT AT ALL - tooltip is handled separately
      };
    });

    candlestickSeriesRef.current.setMarkers(markers);
    markerDataRef.current = markerData;
  }, [transactions, klines, interval]);

  useEffect(() => {
    return () => {
      if (chartRef.current && crosshairMoveHandlerRef.current) {
        chartRef.current.unsubscribeCrosshairMove(crosshairMoveHandlerRef.current);
        crosshairMoveHandlerRef.current = null;
      }
      if (resizeHandlerRef.current) {
        window.removeEventListener('resize', resizeHandlerRef.current);
        resizeHandlerRef.current = null;
      }
      if (markerTooltipRef.current && markerTooltipRef.current.parentNode) {
        markerTooltipRef.current.parentNode.removeChild(markerTooltipRef.current);
        markerTooltipRef.current = null;
      }
      if (indicatorSyncHandlerRef.current && chartRef.current) {
        chartRef.current.timeScale().unsubscribeVisibleLogicalRangeChange(indicatorSyncHandlerRef.current);
        indicatorSyncHandlerRef.current = null;
      }
      if (indicatorChartRef.current) {
        indicatorChartRef.current.remove();
        indicatorChartRef.current = null;
      }
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [symbol]);
  
  const toggleIndicator = (name) => {
    setIndicators(prev => ({ ...prev, [name]: !prev[name] }));
  };
  
  const intervals = [
    { value: '1m', label: '1m' },
    { value: '5m', label: '5m' },
    { value: '15m', label: '15m' },
    { value: '30m', label: '30m' },
    { value: '1h', label: '1h' },
    { value: '4h', label: '4h' },
    { value: '1d', label: '1D' },
    { value: '1w', label: '1W' },
    { value: '1M', label: '1M' }
  ];
  
  return (
    <div className="trading-chart-container">
      <div className="chart-header">
        {onSymbolChange && tradingPairs.length > 0 ? (
          <select 
            value={symbol} 
            onChange={(e) => onSymbolChange(e.target.value)}
            className="chart-symbol-dropdown"
          >
            {tradingPairs.map(pair => (
              <option key={pair.id} value={pair.id}>
                {pair.display_name || pair.id}
              </option>
            ))}
          </select>
        ) : (
          <h3>{baseAsset} / USDT</h3>
        )}
        <div className="interval-selector">
          {intervals.map(int => (
            <button
              key={int.value}
              className={`interval-btn ${interval === int.value ? 'active' : ''}`}
              onClick={() => setInterval(int.value)}
            >
              {int.label}
            </button>
          ))}
        </div>
      </div>
      
      <div className="chart-main-wrapper">
        <div 
          ref={(el) => {
            chartContainerRef.current = el;
            if (el && !chartReady) {
              console.log('Chart container mounted, setting ready state');
              setChartReady(true);
            }
          }}
          className="chart-main" 
          style={{ 
            width: '100%', 
            height: '600px',
            minHeight: '600px',
            display: 'block',
            position: 'relative',
            margin: 0,
            border: 'none',
            boxSizing: 'border-box',
            overflow: 'visible'
          }} 
        />
        {(loading || klines.length === 0) && (
          <div className="chart-overlay">Loading chart data...</div>
        )}
        {error && (
          <div className="chart-overlay error">Error: {error}</div>
        )}
      </div>
      
      {(indicators.rsi || indicators.macd || indicators.stoch || indicators.atr) && (
        <div ref={indicatorContainerRef} className="chart-indicator" />
      )}
      
      <div className="chart-controls">
        <div className="control-section">
          <span className="section-label">Moving Averages:</span>
          <button 
            className={`toggle-btn ${indicators.ma7 ? 'active' : ''}`}
            onClick={() => toggleIndicator('ma7')}
            title="7-period Moving Average - Shows short-term price trends"
          >
            MA 7
          </button>
          <button 
            className={`toggle-btn ${indicators.ma25 ? 'active' : ''}`}
            onClick={() => toggleIndicator('ma25')}
            title="25-period Moving Average - Shows medium-term price trends"
          >
            MA 25
          </button>
          <button 
            className={`toggle-btn ${indicators.ma99 ? 'active' : ''}`}
            onClick={() => toggleIndicator('ma99')}
            title="99-period Moving Average - Shows long-term price trends"
          >
            MA 99
          </button>
        </div>
        
        <div className="control-section">
          <span className="section-label">Oscillators:</span>
          <button 
            className={`toggle-btn ${indicators.rsi ? 'active' : ''}`}
            onClick={() => toggleIndicator('rsi')}
            title="Relative Strength Index - Measures overbought (>70) and oversold (<30) conditions"
          >
            RSI
          </button>
          <button 
            className={`toggle-btn ${indicators.macd ? 'active' : ''}`}
            onClick={() => toggleIndicator('macd')}
            title="Moving Average Convergence Divergence - Shows trend strength and direction changes"
          >
            MACD
          </button>
          <button 
            className={`toggle-btn ${indicators.stoch ? 'active' : ''}`}
            onClick={() => toggleIndicator('stoch')}
            title="Stochastic Oscillator - Compares closing price to price range over time (overbought >80, oversold <20)"
          >
            Stochastic
          </button>
          <button 
            className={`toggle-btn ${indicators.atr ? 'active' : ''}`}
            onClick={() => toggleIndicator('atr')}
            title="Average True Range - Measures market volatility (higher values = more volatility)"
          >
            ATR
          </button>
        </div>
        
        <div className="control-section">
          <span className="section-label">Other:</span>
          <button 
            className={`toggle-btn ${indicators.bb ? 'active' : ''}`}
            onClick={() => toggleIndicator('bb')}
            title="Bollinger Bands - Shows price volatility with upper/lower bands (price touching bands may indicate reversal)"
          >
            Bollinger Bands
          </button>
          <button 
            className={`toggle-btn ${indicators.volume ? 'active' : ''}`}
            onClick={() => toggleIndicator('volume')}
            title="Trading Volume - Shows number of coins traded (high volume confirms price moves)"
          >
            Volume
          </button>
        </div>
      </div>
    </div>
  );
};

export default TradingChart;
