import React, { useState } from 'react';
import axios from 'axios';
import './ValidationPopup.css';

const ValidationPopup = ({ isVisible, onClose, onSync }) => {
    const [validationData, setValidationData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const runValidation = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await axios.post('/api/validate-portfolio');
            setValidationData(response.data);
        } catch (err) {
            console.error('Validation error:', err);
            setError(err.response?.data?.error || 'Failed to validate portfolio');
        }
        setLoading(false);
    };

    const handleSync = async () => {
        try {
            await onSync(); // Call parent sync function
            setValidationData(null); // Clear validation data to force re-check
        } catch (err) {
            setError('Failed to sync portfolio');
        }
    };

    const handleClose = () => {
        setValidationData(null);
        setError(null);
        onClose();
    };

    if (!isVisible) return null;

    return (
        <div className="validation-popup-overlay">
            <div className="validation-popup">
                <div className="validation-popup-header">
                    <h2>🛡️ Portfolio Failsafe Validation</h2>
                    <button className="close-btn" onClick={handleClose}>×</button>
                </div>

                <div className="validation-popup-content">
                    {!validationData && !loading && (
                        <div className="validation-intro">
                            <p>Compare your calculated portfolio amounts with live exchange data to detect any discrepancies.</p>
                            <button 
                                className="validation-btn primary"
                                onClick={runValidation}
                                disabled={loading}
                            >
                                🔍 Validate Portfolio
                            </button>
                        </div>
                    )}

                    {loading && (
                        <div className="validation-loading">
                            <div className="spinner"></div>
                            <p>Comparing calculated vs live amounts...</p>
                        </div>
                    )}

                    {error && (
                        <div className="validation-error">
                            <h3>❌ Validation Error</h3>
                            <p>{error}</p>
                            <button className="validation-btn secondary" onClick={runValidation}>
                                🔄 Retry
                            </button>
                        </div>
                    )}

                    {validationData && (
                        <div className="validation-results">
                            <div className="validation-summary">
                                {validationData.has_discrepancies ? (
                                    <div className="summary-warning">
                                        <h3>⚠️ Discrepancies Found</h3>
                                        <p>Found {validationData.discrepancies.length} amount discrepancy(ies)</p>
                                    </div>
                                ) : (
                                    <div className="summary-success">
                                        <h3>✅ Portfolio Validated</h3>
                                        <p>All amounts match live data exactly</p>
                                    </div>
                                )}
                                
                                <div className="summary-stats">
                                    <span>Calculated: {validationData.total_calculated_symbols} coins</span>
                                    <span>Live: {validationData.total_live_symbols} coins</span>
                                </div>
                            </div>

                            {validationData.has_discrepancies && (
                                <div className="discrepancies-list">
                                    <h4>Discrepancy Details:</h4>
                                    {validationData.discrepancies.map((disc, index) => (
                                        <div 
                                            key={index} 
                                            className={`discrepancy-item ${disc.severity}`}
                                        >
                                            <div className="discrepancy-header">
                                                <strong>{disc.symbol}</strong>
                                                <span className={`severity-badge ${disc.severity}`}>
                                                    {disc.severity}
                                                </span>
                                            </div>
                                            
                                            <div className="discrepancy-details">
                                                <div className="amount-comparison">
                                                    <div className="calculated">
                                                        <label>Calculated:</label>
                                                        <span>{disc.calculated_amount.toFixed(4)}</span>
                                                    </div>
                                                    <div className="live">
                                                        <label>Live:</label>
                                                        <span>{disc.live_amount.toFixed(4)}</span>
                                                    </div>
                                                </div>
                                                
                                                <div className="difference-info">
                                                    <span className="difference">
                                                        Difference: {disc.difference > 0 ? '+' : ''}{disc.difference.toFixed(4)}
                                                    </span>
                                                    <span className="percentage">
                                                        ({disc.percentage_diff > 0 ? '+' : ''}{disc.percentage_diff}%)
                                                    </span>
                                                    {disc.live_value_usd > 0 && (
                                                        <span className="usd-value">
                                                            ${disc.live_value_usd.toFixed(2)} USD
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div className="validation-actions">
                                {validationData.has_discrepancies && (
                                    <button 
                                        className="validation-btn primary"
                                        onClick={handleSync}
                                    >
                                        🔄 Sync & Fix Discrepancies
                                    </button>
                                )}
                                
                                <button 
                                    className="validation-btn secondary"
                                    onClick={runValidation}
                                >
                                    🔍 Re-validate
                                </button>
                                
                                <button 
                                    className="validation-btn tertiary"
                                    onClick={handleClose}
                                >
                                    Close
                                </button>
                            </div>

                            <div className="validation-timestamp">
                                <small>Validated: {new Date(validationData.validation_timestamp).toLocaleString()}</small>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ValidationPopup;
