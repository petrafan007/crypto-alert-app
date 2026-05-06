import React, { useState, useEffect } from 'react';
import axios from 'axios';
import ReportModal from './ReportModal';
import './CoinAnalysisTable.css';

export default function CoinAnalysisTable() {
  const [coinAnalyses, setCoinAnalyses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [runningAnalysis, setRunningAnalysis] = useState({});
  const [showReportModal, setShowReportModal] = useState(false);
  const [selectedReport, setSelectedReport] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState('');

  useEffect(() => {
    fetchCoinAnalyses();
  }, []);

  const fetchCoinAnalyses = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/ai/coin-analysis', { withCredentials: true });
      // Filter only portfolio coins
      const portfolioCoins = response.data.filter(coin => coin.source === 'portfolio');
      setCoinAnalyses(portfolioCoins);
    } catch (error) {
      console.error('Error fetching portfolio coin analyses:', error);
      setError('Failed to load portfolio coin analyses');
    } finally {
      setLoading(false);
    }
  };

  const handleRunAnalysis = async (coin, symbol) => {
    const identifier = coin.coin_id;
    setRunningAnalysis(prev => ({ ...prev, [identifier]: true }));
    try {
      const response = await axios.post('/api/ai/coin-analysis', {
        coin_id: coin.coin_id,
        source: 'portfolio'
      }, { withCredentials: true });
      
      if (response.data.success) {
        // Update the local state with the new analysis
        setCoinAnalyses(prev => 
          prev.map(c => {
            return c.coin_id === identifier 
              ? {
                  ...c,
                  ordinal: response.data.ordinal,
                  date: response.data.date,
                  time: response.data.time,
                  report: response.data.report
                }
              : c;
          })
        );
      }
    } catch (error) {
      console.error('Error running analysis:', error);
      alert('Failed to run analysis. Please try again.');
    } finally {
      setRunningAnalysis(prev => ({ ...prev, [identifier]: false }));
    }
  };

  const formatTime = (timeStr) => {
    if (!timeStr) return '';
    try {
      const [hours, minutes] = timeStr.split(':');
      return `${hours}:${minutes}`;
    } catch {
      return timeStr;
    }
  };

  const showReport = (report, symbol) => {
    setSelectedReport(report);
    setSelectedSymbol(symbol);
    setShowReportModal(true);
  };

  if (loading) {
    return (
      <div className="coin-analysis-loading">
        <p>Loading coin analyses...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="coin-analysis-error">
        <p>Error: {error}</p>
        <button onClick={fetchCoinAnalyses} className="btn btn-primary">
          Retry
        </button>
      </div>
    );
  }

  if (coinAnalyses.length === 0) {
    return (
      <div className="coin-analysis-empty">
        <p>No portfolio coins found for analysis.</p>
        <p>Add some coins to your portfolio to get started.</p>
      </div>
    );
  }

  return (
    <div className="coin-analysis-table">
      <div className="table-header">
        <div className="header-cell">Portfolio Coins</div>
        <div className="header-cell">Analysis</div>
        <div className="header-cell">Date/Time</div>
        <div className="header-cell">Report</div>
      </div>
      <div className="table-body">
        {coinAnalyses.map((coin) => {
          const identifier = coin.coin_id;
          return (
            <div key={identifier} className="table-row">
              <div className="cell coin-cell">
                <span className="coin-symbol">{coin.symbol}</span>
              </div>
              
              <div className="cell analysis-cell">
                <button
                  className={`btn btn-primary ${runningAnalysis[identifier] ? 'loading' : ''}`}
                  onClick={() => handleRunAnalysis(coin, coin.symbol)}
                  disabled={runningAnalysis[identifier]}
                >
                  {runningAnalysis[identifier] ? 'Running...' : 'Run Analysis'}
                </button>
              </div>
            
            <div className="cell datetime-cell">
              {coin.date && coin.time ? (
                <div className="datetime-info">
                  <div className="date">{coin.date}</div>
                  <div className="time">{formatTime(coin.time)}</div>
                  {coin.ordinal > 0 && (
                    <div className="ordinal">#{coin.ordinal}</div>
                  )}
                </div>
              ) : (
                <span className="no-analysis">No analysis yet</span>
              )}
            </div>
            
            <div className="cell report-cell">
              {coin.report ? (
                <div className="report-content">
                  <div className="report-preview">
                    {coin.report.length > 150 
                      ? `${coin.report.substring(0, 150)}...` 
                      : coin.report
                    }
                  </div>
                  <button 
                    className="btn btn-secondary btn-sm"
                    onClick={() => showReport(coin.report, coin.symbol)}
                  >
                    View Full
                  </button>
                </div>
              ) : (
                <span className="no-report">No report available</span>
              )}
            </div>
          </div>
        );
        })}
      </div>

      <ReportModal
        isVisible={showReportModal}
        onClose={() => setShowReportModal(false)}
        report={selectedReport}
        title={`Analysis Report - ${selectedSymbol}`}
      />
    </div>
  );
} 