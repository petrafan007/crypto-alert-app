import React, { useState, useEffect } from 'react';
import axios from 'axios';

export default function TaxReport({ isLightMode }) {
  const [taxData, setTaxData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedAsset, setSelectedAsset] = useState('all');
  const [selectedYear, setSelectedYear] = useState('all');
  const [sortConfig, setSortConfig] = useState({ key: 'date', direction: 'desc' });
  const [filters, setFilters] = useState({
    type: [],
    asset: [],
    amount: []
  });
  const [editingCell, setEditingCell] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [filterModal, setFilterModal] = useState({ show: false, column: null });
  const [addTransactionModal, setAddTransactionModal] = useState(false);
  const [newTransaction, setNewTransaction] = useState({
    date: '',
    type: 'BUY',
    asset: '',
    amount: '',
    proceeds: '',
    cost_basis: '',
    gain_loss: '',
    fee: '',
    description: '',
    status: 'completed',
    details: '',
    avg_entry: '',
    exchange: 'manual'
  });
  const [manualInvestmentInput, setManualInvestmentInput] = useState('0.00');
  const [manualInvestmentSaving, setManualInvestmentSaving] = useState(false);
  const [manualInvestmentFeedback, setManualInvestmentFeedback] = useState({ type: null, message: '' });
  const [showContributionModal, setShowContributionModal] = useState(false);

  useEffect(() => {
    fetchTaxReport();
  }, []);

  const fetchTaxReport = async () => {
    try {
      setLoading(true);
      const response = await axios.get('/api/tax-report', { withCredentials: true });
      setTaxData(response.data);
      const manualAmount = parseFloat(response.data?.summary?.manual_invested_amount ?? 0) || 0;
      setManualInvestmentInput(manualAmount.toFixed(2));
      setManualInvestmentFeedback({ type: null, message: '' });
      setShowContributionModal(false);
    } catch (err) {
      console.error('Error fetching tax report:', err);
      setError('Failed to load tax report');
    } finally {
      setLoading(false);
    }
  };

  const syncAndRefresh = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Sync logs from exchange to pull latest transactions
      await axios.post('/api/logs/sync', {}, { withCredentials: true });
      
      // Then fetch the updated tax report
      const response = await axios.get('/api/tax-report', { withCredentials: true });
      setTaxData(response.data);
    } catch (err) {
      console.error('Error syncing and refreshing tax report:', err);
      setError('Failed to sync logs or load tax report');
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(amount);
  };

  const formatNumber = (num) => {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 8
    }).format(num);
  };

  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const sortData = (data, key) => {
    if (!key) return data;
    
    return [...data].sort((a, b) => {
      let aVal = a[key];
      let bVal = b[key];
      
      // Handle numeric values
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal;
      }
      
      // Handle string values
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortConfig.direction === 'asc' ? 
          aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      
      // Handle undefined/null values
      if (aVal === undefined || aVal === null) aVal = '';
      if (bVal === undefined || bVal === null) bVal = '';
      
      return sortConfig.direction === 'asc' ? 
        String(aVal).localeCompare(String(bVal)) : 
        String(bVal).localeCompare(String(aVal));
    });
  };

  const getSortIcon = (key) => {
    if (sortConfig.key !== key) return '';
    return sortConfig.direction === 'asc' ? '▲' : '▼';
  };

  const getDistinctValues = (key) => {
    if (!taxData) return [];
    const values = [...new Set(taxData.transactions.map(tx => tx[key]).filter(Boolean))];
    return values.sort();
  };

  const applyFilters = (data) => {
    return data.filter(tx => {
      if (filters.type.length > 0 && !filters.type.includes(tx.type)) return false;
      if (filters.asset.length > 0 && !filters.asset.includes(tx.asset)) return false;
      if (filters.amount.length > 0 && !filters.amount.includes(tx.amount)) return false;
      return true;
    });
  };

  const handleFilterChange = (filterKey, value, checked) => {
    setFilters(prev => ({
      ...prev,
      [filterKey]: checked 
        ? [...prev[filterKey], value]
        : prev[filterKey].filter(v => v !== value)
    }));
  };

  const clearFilters = () => {
    setFilters({
      type: [],
      asset: [],
      amount: []
    });
  };

  const openContributionModal = async () => {
    try {
      const response = await axios.get('/api/tax/manual-investment', { withCredentials: true });
      const amount = parseFloat(response.data?.amount ?? manualInvestmentInput) || 0;
      setManualInvestmentInput(amount.toFixed(2));
    } catch (err) {
      console.error('Failed to fetch manual investment amount:', err);
    }
    setManualInvestmentFeedback({ type: null, message: '' });
    window.scrollTo({ top: 0, behavior: 'auto' });
    setShowContributionModal(true);
  };

  const openFilterModal = (column) => {
    setFilterModal({ show: true, column });
  };

  const closeFilterModal = () => {
    setFilterModal({ show: false, column: null });
  };

  const openAddTransactionModal = () => {
    setAddTransactionModal(true);
    // Set default date to today
    const today = new Date().toISOString().split('T')[0];
    setNewTransaction(prev => ({ ...prev, date: today }));
  };

  const closeAddTransactionModal = () => {
    setAddTransactionModal(false);
    // Reset form
    setNewTransaction({
      date: '',
      type: 'BUY',
      asset: '',
      amount: '',
      proceeds: '',
      cost_basis: '',
      gain_loss: '',
      fee: '',
      description: '',
      status: 'completed',
      details: '',
      avg_entry: '',
      exchange: 'manual'
    });
  };

  const handleAddTransaction = async () => {
    try {
      // Validate required fields
      if (!newTransaction.date || !newTransaction.type || !newTransaction.asset || !newTransaction.amount) {
        alert('Please fill in all required fields: Date, Type, Asset, and Amount');
        return;
      }

      const response = await axios.post('/api/transactions', newTransaction, { withCredentials: true });
      
      if (response.data.success) {
        // Refresh the tax report data
        await fetchTaxReport();
        closeAddTransactionModal();
        alert('Transaction added successfully!');
      } else {
        alert('Error: ' + (response.data.error || 'Failed to add transaction'));
      }
    } catch (err) {
      console.error('Error adding transaction:', err);
      alert('Failed to add transaction: ' + (err.response?.data?.error || err.message));
    }
  };

  const handleManualInvestmentSave = async () => {
    const amount = parseFloat(manualInvestmentInput);
    if (Number.isNaN(amount)) {
      setManualInvestmentFeedback({ type: 'error', message: 'Enter a valid dollar amount.' });
      return;
    }

    try {
      setManualInvestmentSaving(true);
      await axios.post('/api/tax/manual-investment', { amount }, { withCredentials: true });
      await fetchTaxReport();
      setManualInvestmentFeedback({ type: 'success', message: 'Saved!' });
      setShowContributionModal(false);
    } catch (err) {
      console.error('Failed to update manual investment amount:', err);
      setManualInvestmentFeedback({
        type: 'error',
        message: err.response?.data?.error || 'Failed to save amount.'
      });
    } finally {
      setManualInvestmentSaving(false);
    }
  };

  const closeContributionModal = () => {
    setShowContributionModal(false);
    setManualInvestmentFeedback({ type: null, message: '' });
  };

  const handleTransactionInputChange = (field, value) => {
    setNewTransaction(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const startEdit = (rowIndex, columnKey, value) => {
    setEditingCell({ rowIndex, columnKey });
    setEditValue(value || '');
  };

  const saveEdit = async () => {
    if (!editingCell) return;
    
    try {
      const { rowIndex, columnKey } = editingCell;
      const tx = taxData.transactions[rowIndex];
      
      await axios.post('/api/logs/update', {
        id: tx.id,
        field: columnKey,
        value: editValue
      }, { withCredentials: true });
      
      // Update local state
      setTaxData(prev => ({
        ...prev,
        transactions: prev.transactions.map((t, i) => 
          i === rowIndex ? { ...t, [columnKey]: editValue } : t
        )
      }));
      
      setEditingCell(null);
      setEditValue('');
    } catch (err) {
      console.error('Error saving edit:', err);
      alert('Failed to save changes');
    }
  };

  const cancelEdit = () => {
    setEditingCell(null);
    setEditValue('');
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      saveEdit();
    } else if (e.key === 'Escape') {
      cancelEdit();
    }
  };

  const exportToCSV = () => {
    if (!taxData) return;
    
    const headers = ['Date', 'Type', 'Asset', 'Amount', 'Price Traded At', 'Proceeds', 'Fee', 'Cost Basis', 'Gain/Loss', 'Gain/Loss Type', 'TxID'];
    const csvContent = [
      headers.join(','),
      ...applyFilters(sortData(taxData.transactions, sortConfig.key)).map(tx => [
        tx.date,
        tx.type,
        tx.asset,
        tx.amount,
        tx.price_sold_at || '',
        tx.proceeds,
        tx.fee,
        tx.cost_basis,
        tx.gain_loss,
        tx.gain_loss_type,
        tx.txid
      ].join(','))
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'tax_report.csv';
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const exportToExcel = () => {
    // For now, just export as CSV with .xlsx extension
    exportToCSV();
  };

  const filterTransactions = () => {
    if (!taxData) return [];
    
    let filtered = taxData.transactions;
    
    if (selectedAsset !== 'all') {
      filtered = filtered.filter(tx => tx.asset === selectedAsset);
    }
    
    if (selectedYear !== 'all') {
      filtered = filtered.filter(tx => tx.date.startsWith(selectedYear));
    }
    
    return filtered;
  };

  const getYears = () => {
    if (!taxData) return [];
    const years = [...new Set(taxData.transactions.map(tx => tx.date.substring(0, 4)))];
    return years.sort();
  };

  const getAssets = () => {
    if (!taxData) return [];
    return taxData.summary.assets_traded.sort();
  };

  if (loading) {
    return (
      <div style={{ 
        padding: '24px',
        textAlign: 'center',
        color: '#4fd1c5'
      }}>
        Loading tax report...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ 
        padding: '24px',
        color: '#f56565',
        textAlign: 'center',
        background: 'rgba(245, 101, 101, 0.1)',
        borderRadius: 8,
        border: '1px solid rgba(245, 101, 101, 0.3)'
      }}>
        {error}
      </div>
    );
  }

  const filteredTransactions = filterTransactions();
  const filteredAndSortedTransactions = applyFilters(sortData(filteredTransactions, sortConfig.key));
  const manualInvestedAmount = parseFloat(taxData?.summary?.manual_invested_amount ?? 0) || 0;
  const manualInvestedUpdatedAt = taxData?.summary?.manual_invested_updated_at
    ? new Date(taxData.summary.manual_invested_updated_at).toLocaleString()
    : null;

  return (
    <div className="main-container tax-report-container">
      <div className="table-container">
        <div className="table-header">
          <h2 className="table-title">Tax Report</h2>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <select
              value={selectedAsset}
              onChange={(e) => setSelectedAsset(e.target.value)}
              className="tax-report-selector"
            >
              <option value="all">All Assets</option>
              {getAssets().map(asset => (
                <option key={asset} value={asset}>{asset}</option>
              ))}
            </select>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(e.target.value)}
              className="tax-report-selector"
            >
              <option value="all">All Years</option>
              {getYears().map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
            <button 
              className="btn"
              onClick={openContributionModal}
            >
              Enter Contributions
            </button>
            <button 
              className="btn btn-secondary" 
              onClick={clearFilters}
            >
              Clear Filters
            </button>
            <button 
              className="btn" 
              onClick={exportToCSV}
            >
              Export CSV
            </button>
            <button 
              className="btn" 
              onClick={exportToExcel}
            >
              Export Excel
            </button>
            <button 
              className="btn" 
              onClick={syncAndRefresh}
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Manual Contribution Modal */}
        {showContributionModal && (
          <div
            id="contributionModal"
            className="modal-backdrop"
            onClick={(e) => {
              if (e.target.id === 'contributionModal') {
                closeContributionModal();
              }
            }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(0,0,0,0.8)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'center',
              paddingTop: '80px',
              paddingBottom: '40px',
              overflowY: 'auto',
              zIndex: 9999
            }}
          >
            <div style={{ 
              background: '#141a22', 
              borderRadius: 12, 
              padding: '24px', 
              width: '360px', 
              maxWidth: '90%',
              boxShadow: '0 12px 32px rgba(0,0,0,0.45)', 
              border: '1px solid #2c3642',
              position: 'relative'
            }}>
              <h3 style={{ color: '#4fd1c5', marginBottom: '12px' }}>Enter Contributions</h3>
              <p style={{ color: '#cbd5f5', fontSize: '14px', lineHeight: 1.5 }}>
                Enter the total USD value you&apos;ve put into crypto so far, including mined coins at the
                value when you received them and any cash deposits. This baseline is used to measure your
                overall gain or loss.
              </p>
              <p style={{ color: '#94a3b8', fontSize: '13px', marginTop: '6px' }}>
                Current baseline: <strong>{formatCurrency(manualInvestedAmount)}</strong>
              </p>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
                <input
                  type="number"
                  step="0.01"
                  value={manualInvestmentInput}
                  onChange={(e) => setManualInvestmentInput(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: '1px solid #334155',
                    background: '#0f141c',
                    color: '#f7fafc',
                    fontSize: 16
                  }}
                />
              </div>
              {manualInvestmentFeedback.message && (
                <div style={{
                  marginTop: '10px',
                  color: manualInvestmentFeedback.type === 'error' ? '#f56565' : '#4fd1c5',
                  fontSize: '13px'
                }}>
                  {manualInvestmentFeedback.message}
                </div>
              )}
              {manualInvestedUpdatedAt && (
                <div style={{ marginTop: '8px', color: '#94a3b8', fontSize: '12px' }}>
                  Last updated {manualInvestedUpdatedAt}
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '20px' }}>
                <button className="btn btn-secondary" onClick={closeContributionModal}>
                  Cancel
                </button>
                <button className="btn" onClick={handleManualInvestmentSave} disabled={manualInvestmentSaving}>
                  {manualInvestmentSaving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Summary Cards */}
        {taxData && (
          <div className="tax-summary-cards">
            <div className="tax-summary-card">
              <h3>Total Gain/Loss</h3>
              <div className={`value ${taxData.summary.total_gain_loss >= 0 ? 'positive' : 'negative'}`}>
                {formatCurrency(taxData.summary.total_gain_loss)}
              </div>
            </div>

            <div className="tax-summary-card">
              <h3>Current Holdings</h3>
              <div className="value">
                {formatCurrency(taxData.summary.current_holdings_value || 0)}
              </div>
            </div>

            <div className="tax-summary-card">
              <h3>Total Transactions</h3>
              <div className="value">
                {taxData.summary.total_transactions}
              </div>
            </div>
          </div>
        )}

        {/* Current Holdings */}
        {taxData && taxData.current_holdings && Object.keys(taxData.current_holdings).length > 0 && (
          <div style={{ marginBottom: '24px' }}>
            <h3 style={{ color: '#4fd1c5', marginBottom: '16px', textAlign: 'center' }}>Current Holdings</h3>
            <div style={{
              background: '#1a1f23',
              border: '1px solid #333',
              borderRadius: '8px',
              padding: '16px',
              width: 'fit-content',
              margin: '0 auto'
            }}>
              <table style={{ width: 'auto', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '8px 12px', color: '#4fd1c5', width: '60px' }}>Asset</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', color: '#4fd1c5', width: '80px' }}>Amount</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', color: '#4fd1c5', width: '90px' }}>Cost Basis</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', color: '#4fd1c5', width: '100px' }}>Avg Price/Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(taxData.current_holdings).map(([asset, holding]) => (
                    <tr key={asset}>
                      <td style={{ padding: '8px 12px', color: '#fff' }}>{asset}</td>
                      <td style={{ textAlign: 'right', padding: '8px 12px', color: '#fff' }}>
                        {formatNumber(holding.amount)}
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 12px', color: '#fff' }}>
                        {formatCurrency(holding.cost_basis)}
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 12px', color: '#fff' }}>
                        {formatCurrency(holding.avg_price_per_unit)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Transaction Log Caption with Add Transaction Button */}
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center', 
          marginBottom: '16px' 
        }}>
          <h3 style={{ color: '#4fd1c5', margin: 0 }}>Transaction Log</h3>
          <button 
            className="btn"
            onClick={openAddTransactionModal}
            style={{ 
              fontSize: '14px',
              padding: '8px 16px'
            }}
          >
            Add Transaction
          </button>
        </div>

        {/* Transactions Table */}
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th onClick={() => handleSort('date')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Date {getSortIcon('date')}
              </th>
              <th style={{ textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <span onClick={() => handleSort('type')} style={{ cursor: 'pointer' }}>
                    Type {getSortIcon('type')}
                  </span>
                  <button 
                    onClick={() => openFilterModal('type')}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: filters.type.length > 0 ? '#4fd1c5' : '#666',
                      cursor: 'pointer',
                      fontSize: '12px',
                      padding: '2px 4px'
                    }}
                  >
                    🔍
                  </button>
                </div>
              </th>
              <th style={{ textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <span onClick={() => handleSort('asset')} style={{ cursor: 'pointer' }}>
                    Asset {getSortIcon('asset')}
                  </span>
                  <button 
                    onClick={() => openFilterModal('asset')}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: filters.asset.length > 0 ? '#4fd1c5' : '#666',
                      cursor: 'pointer',
                      fontSize: '12px',
                      padding: '2px 4px'
                    }}
                  >
                    🔍
                  </button>
                </div>
              </th>
              <th style={{ textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <span onClick={() => handleSort('amount')} style={{ cursor: 'pointer' }}>
                    Amount {getSortIcon('amount')}
                  </span>
                  <button 
                    onClick={() => openFilterModal('amount')}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: filters.amount.length > 0 ? '#4fd1c5' : '#666',
                      cursor: 'pointer',
                      fontSize: '12px',
                      padding: '2px 4px'
                    }}
                  >
                    🔍
                  </button>
                </div>
              </th>
              <th onClick={() => handleSort('price_sold_at')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Price Traded At {getSortIcon('price_sold_at')}
              </th>
              <th onClick={() => handleSort('proceeds')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Proceeds {getSortIcon('proceeds')}
              </th>
              <th onClick={() => handleSort('fee')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Fee {getSortIcon('fee')}
              </th>
              <th onClick={() => handleSort('cost_basis')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Cost Basis {getSortIcon('cost_basis')}
              </th>
              <th onClick={() => handleSort('gain_loss')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Gain/Loss {getSortIcon('gain_loss')}
              </th>
              <th onClick={() => handleSort('gain_loss_type')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                Type {getSortIcon('gain_loss_type')}
              </th>
              <th onClick={() => handleSort('txid')} style={{ cursor: 'pointer', textAlign: 'center', padding: '8px 12px', color: '#4fd1c5' }}>
                TxID {getSortIcon('txid')}
              </th>
            </tr>
          </thead>
            <tbody>
              {filteredAndSortedTransactions.length === 0 ? (
                <tr>
                  <td colSpan="11" style={{ textAlign: 'center', padding: '16px', color: '#999' }}>
                    No transactions found
                  </td>
                </tr>
              ) : (
                filteredAndSortedTransactions.map((tx, index) => (
                  <tr key={tx.id}>
                    {['date', 'type', 'asset', 'amount', 'price_sold_at', 'proceeds', 'fee', 'cost_basis', 'gain_loss', 'gain_loss_type', 'txid'].map(columnKey => (
                      <td 
                        key={columnKey}
                        style={{ textAlign: 'center', padding: '8px 12px' }}
                        onDoubleClick={() => startEdit(index, columnKey, tx[columnKey])}
                      >
                        {editingCell && editingCell.rowIndex === index && editingCell.columnKey === columnKey ? (
                          <input
                            type="text"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onKeyDown={handleKeyPress}
                            onBlur={saveEdit}
                            autoFocus
                            style={{
                              width: '100%',
                              padding: '4px 8px',
                              background: '#1a1f23',
                              color: '#fff',
                              border: '1px solid #4fd1c5',
                              borderRadius: '4px',
                              fontSize: '12px'
                            }}
                          />
                        ) : (
                          <span style={{ cursor: 'pointer' }}>
                            {columnKey === 'date' ? new Date(tx[columnKey]).toLocaleDateString() :
                             columnKey === 'type' ? (
                               <span style={{
                                 padding: '2px 8px',
                                 borderRadius: '4px',
                                 fontSize: '12px',
                                 fontWeight: 'bold',
                                 background: tx[columnKey] === 'BUY' ? 'rgba(72, 187, 120, 0.2)' : 
                                           tx[columnKey] === 'SELL' ? 'rgba(245, 101, 101, 0.2)' : 
                                           'rgba(79, 209, 197, 0.2)',
                                 color: tx[columnKey] === 'BUY' ? '#48bb78' : 
                                        tx[columnKey] === 'SELL' ? '#f56565' : '#4fd1c5'
                               }}>
                                 {tx[columnKey]}
                               </span>
                             ) :
                             columnKey === 'amount' ? formatNumber(tx[columnKey]) :
                             columnKey === 'proceeds' ? (tx[columnKey] > 0 ? formatCurrency(tx[columnKey]) : '—') :
                             columnKey === 'fee' ? (tx[columnKey] > 0 ? formatCurrency(tx[columnKey]) : '—') :
                             columnKey === 'cost_basis' ? (tx[columnKey] > 0 ? formatCurrency(tx[columnKey]) : '—') :
                             columnKey === 'gain_loss' ? (tx[columnKey] !== null ? formatCurrency(tx[columnKey]) : '—') :
                             columnKey === 'gain_loss_type' ? (
                               tx[columnKey] ? (
                                 <span style={{
                                   padding: '2px 6px',
                                   borderRadius: '4px',
                                   fontSize: '11px',
                                   fontWeight: 'bold',
                                   background: tx[columnKey] === 'short_term' ? 'rgba(72, 187, 120, 0.2)' : 'rgba(245, 101, 101, 0.2)',
                                   color: tx[columnKey] === 'short_term' ? '#48bb78' : '#f56565'
                                 }}>
                                   {tx[columnKey] === 'short_term' ? 'ST Gain' : 'Loss'}
                                 </span>
                               ) : '—'
                             ) :
                             tx[columnKey] || '—'}
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

      {/* Filter Modal */}
      {filterModal.show && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999
        }}>
          <div style={{
            background: '#1a1f23',
            border: '1px solid #333',
            borderRadius: '8px',
            padding: '24px',
            maxWidth: '400px',
            width: '90%',
            maxHeight: '80vh',
            overflow: 'auto'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ color: '#4fd1c5', margin: 0, textTransform: 'capitalize' }}>
                Filter by {filterModal.column}
              </h3>
              <button
                onClick={closeFilterModal}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#fff',
                  fontSize: '24px',
                  cursor: 'pointer',
                  padding: '4px'
                }}
              >
                ×
              </button>
            </div>

            <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
              {getDistinctValues(filterModal.column).map(value => (
                <label key={value} style={{ 
                  display: 'block', 
                  marginBottom: '8px',
                  color: '#fff',
                  fontSize: '14px'
                }}>
                  <input
                    type="checkbox"
                    checked={filters[filterModal.column].includes(value)}
                    onChange={(e) => handleFilterChange(filterModal.column, value, e.target.checked)}
                    style={{ marginRight: '8px' }}
                  />
                  {value}
                </label>
              ))}
            </div>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '20px' }}>
              <button
                onClick={closeFilterModal}
                style={{
                  padding: '8px 16px',
                  background: '#666',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer'
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Transaction Modal */}
      {addTransactionModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999
        }}>
          <div style={{
            background: 'var(--card-bg, #1a1f23)',
            border: '1px solid var(--border-color, #333)',
            borderRadius: '8px',
            padding: '24px',
            maxWidth: '600px',
            width: '90%',
            maxHeight: '80vh',
            overflow: 'auto',
            color: 'var(--text-primary, #fff)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ color: 'var(--primary-color, #4fd1c5)', margin: 0 }}>
                Add Transaction
              </h3>
              <button
                onClick={closeAddTransactionModal}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-primary, #fff)',
                  fontSize: '24px',
                  cursor: 'pointer',
                  padding: '4px'
                }}
              >
                ×
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
              {/* Date - Required */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: 'bold' }}>
                  Date *
                </label>
                <input
                  type="date"
                  value={newTransaction.date}
                  onChange={(e) => handleTransactionInputChange('date', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                  required
                />
              </div>

              {/* Type - Required */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: 'bold' }}>
                  Type *
                </label>
                <select
                  value={newTransaction.type}
                  onChange={(e) => handleTransactionInputChange('type', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                  required
                >
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                  <option value="TRANSFER">TRANSFER</option>
                  <option value="GIFT">GIFT</option>
                  <option value="BONUS">BONUS</option>
                  <option value="RECEIVE">RECEIVE</option>
                </select>
              </div>

              {/* Asset - Required */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: 'bold' }}>
                  Asset *
                </label>
                <input
                  type="text"
                  placeholder="BTC, ETH, SOL, etc."
                  value={newTransaction.asset}
                  onChange={(e) => handleTransactionInputChange('asset', e.target.value.toUpperCase())}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                  required
                />
              </div>

              {/* Amount - Required */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: 'bold' }}>
                  Amount *
                </label>
                <input
                  type="number"
                  step="any"
                  placeholder="0.00000000"
                  value={newTransaction.amount}
                  onChange={(e) => handleTransactionInputChange('amount', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                  required
                />
              </div>

              {/* Proceeds */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px' }}>
                  Proceeds ($)
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={newTransaction.proceeds}
                  onChange={(e) => handleTransactionInputChange('proceeds', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
              </div>

              {/* Cost Basis */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px' }}>
                  Cost Basis ($)
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={newTransaction.cost_basis}
                  onChange={(e) => handleTransactionInputChange('cost_basis', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
              </div>

              {/* Fee */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px' }}>
                  Fee ($)
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={newTransaction.fee}
                  onChange={(e) => handleTransactionInputChange('fee', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
              </div>

              {/* Avg Entry Price */}
              <div>
                <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px' }}>
                  Price per Unit ($)
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={newTransaction.avg_entry}
                  onChange={(e) => handleTransactionInputChange('avg_entry', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--input-bg, #2a2f36)',
                    color: 'var(--text-primary, #fff)',
                    border: '1px solid var(--border-color, #444)',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
              </div>
            </div>

            {/* Description - Full width */}
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px' }}>
                Description
              </label>
              <input
                type="text"
                placeholder="Optional description"
                value={newTransaction.description}
                onChange={(e) => handleTransactionInputChange('description', e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  background: 'var(--input-bg, #2a2f36)',
                  color: 'var(--text-primary, #fff)',
                  border: '1px solid var(--border-color, #444)',
                  borderRadius: '4px',
                  fontSize: '14px'
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                onClick={closeAddTransactionModal}
                style={{
                  padding: '10px 20px',
                  background: 'var(--secondary-bg, #666)',
                  color: 'var(--text-primary, #fff)',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '14px'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleAddTransaction}
                style={{
                  padding: '10px 20px',
                  background: 'var(--primary-color, #4fd1c5)',
                  color: '#000',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: 'bold'
                }}
              >
                Add Transaction
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
