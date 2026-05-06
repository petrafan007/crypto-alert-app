import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart } from 'lightweight-charts';
import axios from 'axios';
import './TradingChart.css';

const TradingChart = ({ symbol = 'BTCUSDT' }) => {
  // Refs for chart elements
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candlestickSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  
  // State
  const [interval, setInterval] = useState('1d');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [klines, setKlines] = useState([]);
  
  // Indicator toggles
  const [indicators, setIndicators] = useState({
    ma7: false,
    ma25: true,
    ma99: false,
    rsi: true,
    macd: false,
    bb: false,
    stoch: false,
    atr: false,
    volume: true,
    fibonacci: false
  });
  
  const baseAsset = symbol.replace('USDT', '').replace('USD', '');
  
  // Fetch klines and transactions
  useEffect(() => {
    if (!symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      
      try {
        // Fetch klines
        
        setKlines(klinesData);
      } catch (err) {
        console.error('Error fetching klines:', err);
        setError('Failed to load chart data');
      } finally {
        setLoading(false);
      }
    };
    
    fetchKlines();
    
    // Set up polling
    const intervalId = setInterval(fetchKlines, 60000); // Update every minute
    
    return () => clearInterval(intervalId);
  }, [symbol, interval]);
  
  // Render loading state
  if (loading) {
    return <div className="chart-container">Loading chart data...</div>;
  }
  };
  
  
  
  // Initialize chart when klines are loaded or container ref changes
  useEffect(() => {
    console.log('Klines updated, count:', klines.length, 'Container ref:', !!chartContainerRef.current);
    
    const init = () => {
      if (klines.length > 0 && chartContainerRef.current) {
        console.log('Initializing chart...');
        const container = chartContainerRef.current;
        const width = container.clientWidth || 800;
        const height = container.clientHeight || 400;
        
        // Clean up existing chart if any
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
        
        try {
          console.log('Creating chart with dimensions:', width, 'x', height);
          chartRef.current = createChart(container, {
            width,
            height,
            layout: {
              background: { color: '#1e1e1e' },
              textColor: '#d1d4dc',
            },
            grid: {
              vertLines: { color: '#2b2b43' },
              horzLines: { color: '#2b2b43' },
            },
            crosshair: { mode: 1 },
            rightPriceScale: {
              borderColor: '#485c7b',
              scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            timeScale: {
              borderColor: '#485c7b',
              timeVisible: true,
              secondsVisible: false,
            },
          });
          
          // Add candlestick series
          candlestickSeriesRef.current = chartRef.current.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderUpColor: '#26a69a',
            borderDownColor: '#ef5350',
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
          });
          
          // Set the data
          console.log('Setting klines data, count:', klines.length);
          candlestickSeriesRef.current.setData(klines);
          
        } catch (error) {
          console.error('Error initializing chart:', error);
        }
      }
    };
    
    init();
    
    // Handle window resize
    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.resize(
          chartContainerRef.current.clientWidth,
          chartContainerRef.current.clientHeight || 400
        );
      }
    };
    
    window.addEventListener('resize', handleResize);
    
    // Cleanup
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [klines]);
  
  // Initialize chart when klines are loaded
  useEffect(() => {
    if (klines.length === 0 || !chartContainerRef.current) return;
    
    console.log('Initializing chart with', klines.length, 'data points');
    
    // Clean up existing chart if any
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }
    
    const container = chartContainerRef.current;
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 400;
    
    try {
      // Create the main chart
      chartRef.current = createChart(container, {
        width,
        height,
        layout: {
          background: { color: '#1e1e1e' },
          textColor: '#d1d4dc',
        },
        grid: {
          vertLines: { color: '#2b2b43' },
          horzLines: { color: '#2b2b43' },
        },
        crosshair: {
          mode: 1,
        },
        rightPriceScale: {
          borderColor: '#485c7b',
          scaleMargins: {
            top: 0.1,
            bottom: 0.1,
          },
        },
        timeScale: {
          borderColor: '#485c7b',
          timeVisible: true,
          secondsVisible: false,
        },
      });
      
      // Add candlestick series
      candlestickSeriesRef.current = chartRef.current.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderUpColor: '#26a69a',
        borderDownColor: '#ef5350',
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      });
      
      // Add volume series
      volumeSeriesRef.current = chartRef.current.addHistogramSeries({
        color: '#385263',
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      
      // Configure volume scale
      chartRef.current.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },
        borderColor: '#485c7b',
      });
      
      // Set the data
      candlestickSeriesRef.current.setData(klines);
      
      // Add volume data
      const volumeData = klines.map(k => ({
        time: k.time,
        value: k.volume,
        color: k.close >= k.open ? '#26a69a80' : '#ef535080'
      }));
      volumeSeriesRef.current.setData(volumeData);
      
      // Handle window resize
      const handleResize = () => {
        if (chartRef.current && chartContainerRef.current) {
          chartRef.current.resize(
            chartContainerRef.current.clientWidth,
            chartContainerRef.current.clientHeight || 400
          );
        }
      };
      
      window.addEventListener('resize', handleResize);
      
      // Cleanup function
      return () => {
        window.removeEventListener('resize', handleResize);
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
      };
      
    } catch (error) {
      console.error('Error initializing chart:', error);
      setError('Failed to initialize chart');
    }
  }, [klines]);
          background: { color: '#1e1e1e' },
          textColor: '#d1d4dc',
        },
        grid: {
          vertLines: { color: '#2b2b43' },
          horzLines: { color: '#2b2b43' },
        },
        rightPriceScale: {
          borderColor: '#485c7b',
          scaleMargins: {
            top: 0.1,
            bottom: 0.1,
          },
        },
        timeScale: {
          borderColor: '#485c7b',
          visible: false,
        },
      });
    }
    
    // Update data
    candlestickSeriesRef.current.setData(klines);
    
    if (indicators.volume && volumeSeriesRef.current) {
      const volumeData = klines.map(k => ({
        time: k.time,
        value: k.volume,
        color: k.close >= k.open ? '#26a69a80' : '#ef535080'
      }));
      volumeSeriesRef.current.setData(volumeData);
    }
    
    // Sync time scales
    if (chartRef.current && indicatorChartRef.current) {
      chartRef.current.timeScale().subscribeVisibleLogicalRangeChange(timeRange => {
        indicatorChartRef.current.timeScale().setVisibleLogicalRange(timeRange);
      });
    }
    
    // Handle resize
    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth
        });
      }
      if (indicatorChartRef.current && indicatorContainerRef.current) {
        indicatorChartRef.current.applyOptions({
          width: indicatorContainerRef.current.clientWidth
        });
      }
    };
    
    window.addEventListener('resize', handleResize);
    
    return () => {
      window.removeEventListener('resize', handleResize);
    };
    };
    
      // Set up a resize observer to detect when container is actually visible and has dimensions
    const resizeObserver = new ResizeObserver((entries) => {
      for (let entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          console.log('Container has dimensions:', entry.contentRect);
          setContainerMounted(true);
          initChart();
        }
      }
    });

    // Start observing the container
    if (chartContainerRef.current) {
      resizeObserver.observe(chartContainerRef.current);
    }

    // Also try initializing immediately in case the container is already ready
    initChart();
    
    // Set up a retry mechanism as a fallback
    let retryCount = 0;
    const maxRetries = 10;
    const retryInterval = 200; // Increased delay to give more time for layout
    
    const retryInit = setInterval(() => {
      if (chartRef.current || retryCount >= maxRetries) {
        clearInterval(retryInit);
        return;
      }
      
      console.log(`Retrying chart initialization (attempt ${retryCount + 1}/${maxRetries})`);
      initChart();
      retryCount++;
      
      if (retryCount >= maxRetries && !chartRef.current) {
        console.error('Failed to initialize chart after maximum retries');
      }
    }, retryInterval);
    
    // Cleanup function
    return () => {
      clearInterval(retryInit);
      resizeObserver.disconnect();
    };
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
          title: 'RSI (14)'
        });
      }
      rsiSeriesRef.current.setData(calculateRSI(klines, 14));
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
          title: 'MACD'
        });
      }
      if (!macdSignalRef.current) {
        macdSignalRef.current = indicatorChartRef.current.addLineSeries({
          color: '#FF9800',
          lineWidth: 2,
          title: 'Signal'
        });
      }
      if (!macdHistogramRef.current) {
        macdHistogramRef.current = indicatorChartRef.current.addHistogramSeries({
          title: 'Histogram'
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
    if (!candlestickSeriesRef.current || transactions.length === 0) return;
    
    const markers = transactions.map(tx => ({
      time: tx.time,
      position: tx.type === 'BUY' ? 'belowBar' : 'aboveBar',
      color: tx.type === 'BUY' ? '#26a69a' : '#ef5350',
      shape: 'circle',
      text: tx.type === 'BUY' ? 'B' : 'S',
      size: 1
    }));
    
    candlestickSeriesRef.current.setMarkers(markers);
  }, [transactions, klines]);
  
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
  
  if (loading) {
    return (
      <div className="trading-chart-container">
        <div className="chart-loading">Loading chart data...</div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="trading-chart-container">
        <div className="chart-error">Error: {error}</div>
      </div>
    );
  }
  
  // Debug: Show if we have data but no chart
  // Show loading state only if we don't have any data yet
  if (klines.length === 0) {
    return (
      <div className="trading-chart-container">
        <div className="chart-loading">Loading chart data...</div>
      </div>
    );
  }
  
  return (
    <div className="trading-chart-container">
      <div className="chart-header">
        <h3>{baseAsset} / USDT</h3>
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
      
      <div 
        ref={containerRef}
        className="chart-main" 
        style={{ 
          width: '100%', 
          height: '400px',
          minHeight: '400px',
          display: 'block',
          position: 'relative',
          backgroundColor: '#1e1e1e' // Add background to make container visible for debugging
        }}
      >
        {!chartRef.current && klines.length > 0 && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            color: '#fff',
            textAlign: 'center'
          }}>
            Initializing chart...
            <div style={{ fontSize: '12px', marginTop: '10px' }}>
              Container: {chartContainerRef.current ? 'Mounted' : 'Not mounted'}<br />
              Klines: {klines.length}
            </div>
          </div>
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
          >
            MA 7
          </button>
          <button 
            className={`toggle-btn ${indicators.ma25 ? 'active' : ''}`}
            onClick={() => toggleIndicator('ma25')}
          >
            MA 25
          </button>
          <button 
            className={`toggle-btn ${indicators.ma99 ? 'active' : ''}`}
            onClick={() => toggleIndicator('ma99')}
          >
            MA 99
          </button>
        </div>
        
        <div className="control-section">
          <span className="section-label">Oscillators:</span>
          <button 
            className={`toggle-btn ${indicators.rsi ? 'active' : ''}`}
            onClick={() => toggleIndicator('rsi')}
          >
            RSI
          </button>
          <button 
            className={`toggle-btn ${indicators.macd ? 'active' : ''}`}
            onClick={() => toggleIndicator('macd')}
          >
            MACD
          </button>
          <button 
            className={`toggle-btn ${indicators.stoch ? 'active' : ''}`}
            onClick={() => toggleIndicator('stoch')}
          >
            Stochastic
          </button>
          <button 
            className={`toggle-btn ${indicators.atr ? 'active' : ''}`}
            onClick={() => toggleIndicator('atr')}
          >
            ATR
          </button>
        </div>
        
        <div className="control-section">
          <span className="section-label">Other:</span>
          <button 
            className={`toggle-btn ${indicators.bb ? 'active' : ''}`}
            onClick={() => toggleIndicator('bb')}
          >
            Bollinger Bands
          </button>
          <button 
            className={`toggle-btn ${indicators.volume ? 'active' : ''}`}
            onClick={() => toggleIndicator('volume')}
          >
            Volume
          </button>
        </div>
      </div>
    </div>
  );
};

export default TradingChart;
