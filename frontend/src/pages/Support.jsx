import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { FaPaperPlane } from 'react-icons/fa';

export default function Support({ isLightMode }) {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const [formData, setFormData] = useState({
        fullName: '',
        email: '',
        topic: '',
        message: ''
    });
    const [attachment, setAttachment] = useState(null);
    const [sending, setSending] = useState(false);
    const [success, setSuccess] = useState(false);
    const [error, setError] = useState('');

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';
    const inputBg = isLightMode ? '#ffffff' : '#0f0f23';
    const accentColor = '#00b5ad';

    const topics = [
        { value: '', label: 'Select a topic' },
        { value: 'Billing', label: 'Billing' },
        { value: 'Technical Issue', label: 'Technical Issue' },
        { value: 'Suggestions', label: 'Suggestions' },
        { value: 'Questions', label: 'Questions' },
        { value: 'Account Access', label: 'Account Access' },
        { value: 'Content Feedback', label: 'Content Feedback' },
        { value: 'Other', label: 'Other' }
    ];

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
        setError('');
    };

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (file) {
            // Check file size (100 MB limit)
            if (file.size > 100 * 1024 * 1024) {
                setError('File size must be less than 100 MB');
                e.target.value = '';
                return;
            }
            setAttachment(file);
        }
        setError('');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setSuccess(false);

        // Validation
        if (!formData.email) {
            setError('Email address is required');
            return;
        }
        if (!formData.topic) {
            setError('Please select a topic');
            return;
        }
        if (!formData.message) {
            setError('Message is required');
            return;
        }
        if (formData.message.length > 5000) {
            setError('Message must be 5000 characters or less');
            return;
        }

        setSending(true);

        try {
            const submitData = new FormData();
            submitData.append('fullName', formData.fullName);
            submitData.append('email', formData.email);
            submitData.append('topic', formData.topic);
            submitData.append('message', formData.message);
            if (attachment) {
                submitData.append('attachment', attachment);
            }

            await axios.post('/api/support/send', submitData, {
                headers: { 'Content-Type': 'multipart/form-data' },
                withCredentials: true
            });

            setSuccess(true);
            setFormData({ fullName: '', email: '', topic: '', message: '' });
            setAttachment(null);
            // Reset file input
            const fileInput = document.getElementById('attachment-input');
            if (fileInput) fileInput.value = '';
        } catch (err) {
            setError(err.response?.data?.error || 'Failed to send message. Please try again.');
        } finally {
            setSending(false);
        }
    };

    const inputStyle = {
        width: '100%',
        padding: '12px 16px',
        backgroundColor: inputBg,
        border: `1px solid ${borderColor}`,
        borderRadius: '6px',
        color: textColor,
        fontSize: '15px',
        outline: 'none'
    };

    const labelStyle = {
        display: 'block',
        marginBottom: '8px',
        fontWeight: 600,
        color: textColor
    };

    return (
        <div style={{
            padding: '20px',
            maxWidth: '700px',
            margin: '0 auto',
            backgroundColor: bgColor,
            minHeight: '100vh'
        }}>
            <div style={{
                backgroundColor: cardBg,
                borderRadius: '12px',
                padding: '32px',
                border: `1px solid ${borderColor}`
            }}>
                <h1 style={{ color: accentColor, marginBottom: '8px', fontSize: '2rem' }}>Support</h1>
                <p style={{ color: textColor, marginBottom: '32px', lineHeight: '1.6' }}>
                    Need help with your account or the app? Send us a message and we'll respond within 1–2
                    business days.
                </p>

                {success && (
                    <div style={{
                        backgroundColor: isLightMode ? '#d4edda' : '#1e5631',
                        color: isLightMode ? '#155724' : '#a3d9a5',
                        padding: '16px',
                        borderRadius: '8px',
                        marginBottom: '24px'
                    }}>
                        ✓ Your message has been sent successfully! We'll get back to you soon.
                    </div>
                )}

                {error && (
                    <div style={{
                        backgroundColor: isLightMode ? '#f8d7da' : '#5c1e1e',
                        color: isLightMode ? '#721c24' : '#f5a3a3',
                        padding: '16px',
                        borderRadius: '8px',
                        marginBottom: '24px'
                    }}>
                        {error}
                    </div>
                )}

                <form onSubmit={handleSubmit}>
                    {/* Name and Email Row */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
                        <div>
                            <label style={labelStyle}>Full Name</label>
                            <input
                                type="text"
                                name="fullName"
                                value={formData.fullName}
                                onChange={handleChange}
                                placeholder="Optional"
                                style={inputStyle}
                            />
                        </div>
                        <div>
                            <label style={labelStyle}>Email Address <span style={{ color: '#f56565' }}>*</span></label>
                            <input
                                type="email"
                                name="email"
                                value={formData.email}
                                onChange={handleChange}
                                placeholder="name@example.com"
                                required
                                style={inputStyle}
                            />
                        </div>
                    </div>

                    {/* Topic */}
                    <div style={{ marginBottom: '20px' }}>
                        <label style={labelStyle}>Topic <span style={{ color: '#f56565' }}>*</span></label>
                        <select
                            name="topic"
                            value={formData.topic}
                            onChange={handleChange}
                            required
                            style={{ ...inputStyle, cursor: 'pointer' }}
                        >
                            {topics.map(t => (
                                <option key={t.value} value={t.value}>{t.label}</option>
                            ))}
                        </select>
                    </div>

                    {/* Message */}
                    <div style={{ marginBottom: '20px' }}>
                        <label style={labelStyle}>Message <span style={{ color: '#f56565' }}>*</span></label>
                        <textarea
                            name="message"
                            value={formData.message}
                            onChange={handleChange}
                            placeholder="How can we help you?"
                            required
                            rows={8}
                            maxLength={5000}
                            style={{ ...inputStyle, resize: 'vertical', minHeight: '150px' }}
                        />
                        <div style={{ textAlign: 'right', color: textColor, opacity: 0.6, fontSize: '13px', marginTop: '4px' }}>
                            {formData.message.length}/5000 characters
                        </div>
                    </div>

                    {/* Attachment */}
                    <div style={{ marginBottom: '28px' }}>
                        <label style={labelStyle}>Attachment (optional)</label>
                        <div style={{
                            border: `1px solid ${borderColor}`,
                            borderRadius: '6px',
                            padding: '12px 16px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '12px',
                            backgroundColor: inputBg
                        }}>
                            <label
                                htmlFor="attachment-input"
                                style={{
                                    padding: '8px 16px',
                                    backgroundColor: accentColor,
                                    color: 'white',
                                    borderRadius: '4px',
                                    cursor: 'pointer',
                                    fontWeight: 500,
                                    fontSize: '14px'
                                }}
                            >
                                Choose File
                            </label>
                            <input
                                id="attachment-input"
                                type="file"
                                onChange={handleFileChange}
                                style={{ display: 'none' }}
                                accept=".jpg,.jpeg,.png,.gif,.pdf,.doc,.docx,.txt,.csv,.xls,.xlsx"
                            />
                            <span style={{ color: textColor, opacity: 0.7 }}>
                                {attachment ? attachment.name : 'No file chosen'}
                            </span>
                        </div>
                        <p style={{ color: textColor, opacity: 0.6, fontSize: '13px', marginTop: '8px' }}>
                            Images, documents, text, or PDF files only. Max 100 MB.
                        </p>
                    </div>

                    {/* Submit Button */}
                    <div style={{ textAlign: 'right' }}>
                        <button
                            type="submit"
                            disabled={sending}
                            style={{
                                padding: '12px 28px',
                                backgroundColor: accentColor,
                                color: 'white',
                                border: 'none',
                                borderRadius: '6px',
                                fontSize: '16px',
                                fontWeight: 600,
                                cursor: sending ? 'not-allowed' : 'pointer',
                                opacity: sending ? 0.7 : 1,
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '8px'
                            }}
                        >
                            <FaPaperPlane />
                            {sending ? 'Sending...' : 'Send Message'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
