import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './AICopilotSidebar.css';
import { useAuth } from './AuthContext';

export default function AICopilotSidebar() {
  const { isLoggingOut } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [message, setMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const messagesEndRef = useRef(null);
  // Auto-refresh is now always on with a 60-second interval
  const [showSentiment, setShowSentiment] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [selectAll, setSelectAll] = useState(false);
  const [selectedMessages, setSelectedMessages] = useState(new Set());
  const [thinkingDots, setThinkingDots] = useState('.');
  const thinkingPlaceholderIdRef = useRef(null);
  const [username, setUsername] = useState('You');
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const limit = 10;

  // Load current username once
  useEffect(() => {
    (async () => {
      try {
        const r = await axios.get('/api/get-credentials', { withCredentials: true });
        if (r.data && r.data.username) setUsername(r.data.username);
      } catch {}
    })();
  }, []);

  // Check AI status and fetch conversations when sidebar opens or when sentiment filter changes
  useEffect(() => {
    if (isOpen) {
      checkAiStatus();
      fetchConversations(); // Initial fetch when sidebar opens or when filter changes
    }
  }, [isOpen, showSentiment]);

  // Auto-refresh conversations every 60 seconds when sidebar is open
  useEffect(() => {
    const refreshInterval = setInterval(() => {
      if (!isOpen) {
        fetchConversations();
      }
    }, 60000); // 60 seconds
    
    // Initial fetch when component mounts
    if (!isOpen) {
      fetchConversations();
    }
    
    return () => clearInterval(refreshInterval);
  }, [isOpen, showSentiment, searchTerm]); // Add showSentiment and searchTerm to dependencies
  // Animated dots for Thinking… placeholder while loading
  useEffect(() => {
    if (!isLoading) return;
    const iv = setInterval(() => {
      setThinkingDots(prev => (prev.length >= 3 ? '.' : prev + '.'));
    }, 500);
    return () => clearInterval(iv);
  }, [isLoading]);
  
  // Toggle sentiment filter
  const toggleSentimentFilter = () => {
    const newValue = !showSentiment;
    setShowSentiment(newValue);
    // Reset offset and fetch conversations with the new filter
    setOffset(0);
    // Use a small timeout to ensure state is updated before fetching
    setTimeout(() => {
      fetchConversations();
    }, 0);
  };

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    // Only scroll to bottom if we're at the bottom or if it's a new message
    const conversationsContainer = document.querySelector('.conversations-list');
    if (conversationsContainer) {
      const isAtBottom = conversationsContainer.scrollTop + conversationsContainer.clientHeight >= conversationsContainer.scrollHeight - 10;
      if (isAtBottom) {
        scrollToBottom();
      }
    }
  }, [conversations]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const fetchConversations = async (loadMore = false) => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }
      
      if (loadMore) {
        setIsLoadingMore(true);
      } else {
        setIsLoading(true);
      }
      
      const currentOffset = loadMore ? offset : 0;
      
      const params = new URLSearchParams();
      if (searchTerm) params.append('search', searchTerm);
      params.append('limit', limit.toString());
      params.append('offset', currentOffset.toString());
      params.append('include_hidden', 'false'); // Only fetch non-hidden messages
      params.append('filter_sentiment', showSentiment ? 'true' : 'false'); // Filter by sentiment if enabled
      
      const response = await axios.get(`/api/ai/conversations?${params}`, { 
        withCredentials: true 
      });
      
      const newConversations = response.data.conversations || [];
      const total = response.data.total || 0;
      const hasMoreData = response.data.has_more || false;
      
      setTotalCount(total);
      setHasMore(hasMoreData);
      
      if (loadMore) {
        // Append older messages to the end
        const serverKeys = new Set(conversations.map(m => m.id));
        const uniqueNewConvs = newConversations.filter(conv => !serverKeys.has(conv.id));
        setConversations(prev => [...prev, ...uniqueNewConvs]);
        setOffset(currentOffset + limit);
      } else {
        // Only replace if not already loaded more than limit
        if (offset <= limit) {
          const serverKeys = new Set(newConversations.map(m => `${m.sender}|${(m.body || '').trim()}`));
          setConversations(prev => {
            const optimistic = prev.filter(m => m && m.optimistic === true && (
              m.thinking === true || !serverKeys.has(`${m.sender}|${(m.body || '').trim()}`)
            ));
            return [...optimistic, ...newConversations];
          });
          setOffset(limit);
        }
        // If user has loaded more, do not overwrite expanded list
      }
    } catch (error) {
      console.error('Error fetching conversations:', error);
    } finally {
      setIsLoadingMore(false);
    }
  };

  const loadMoreMessages = () => {
    if (!isLoadingMore && hasMore) {
      fetchConversations(true);
    }
  };

  const deleteMessage = async (messageId) => {
    try {
      await axios.delete(`/api/ai/conversations/${messageId}`, { 
        withCredentials: true 
      });
      setConversations(prev => prev.filter(conv => conv.id !== messageId));
    } catch (error) {
      console.error('Error deleting message:', error);
    }
  };

  const archiveMessage = async (messageId) => {
    try {
      await axios.patch(`/api/ai/conversations/${messageId}/archive`, {}, { 
        withCredentials: true 
      });
      setConversations(prev => prev.filter(conv => conv.id !== messageId));
    } catch (error) {
      console.error('Error archiving message:', error);
    }
  };

  const toggleSelectAll = () => {
    if (selectAll) {
      setSelectedMessages(new Set());
    } else {
      setSelectedMessages(new Set(conversations.map(conv => conv.id)));
    }
    setSelectAll(!selectAll);
  };

  const toggleSelectMessage = (messageId) => {
    setSelectedMessages(prev => {
      const newSet = new Set(prev);
      if (newSet.has(messageId)) {
        newSet.delete(messageId);
      } else {
        newSet.add(messageId);
      }
      return newSet;
    });
  };

  const bulkDelete = async () => {
    if (selectedMessages.size === 0) return;
    
    try {
      await Promise.all(
        Array.from(selectedMessages).map(id => 
          axios.delete(`/api/ai/conversations/${id}`, { withCredentials: true })
        )
      );
      setConversations(prev => prev.filter(conv => !selectedMessages.has(conv.id)));
      setSelectedMessages(new Set());
      setSelectAll(false);
    } catch (error) {
      console.error('Error bulk deleting messages:', error);
    }
  };

  const bulkArchive = async () => {
    if (selectedMessages.size === 0) return;
    
    try {
      await Promise.all(
        Array.from(selectedMessages).map(id => 
          axios.patch(`/api/ai/conversations/${id}/archive`, {}, { withCredentials: true })
        )
      );
      setConversations(prev => prev.filter(conv => !selectedMessages.has(conv.id)));
      setSelectedMessages(new Set());
      setSelectAll(false);
    } catch (error) {
      console.error('Error bulk archiving messages:', error);
    }
  };

  const checkAiStatus = async () => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }
      
      // Try to get AI settings to check if AI is enabled
      const response = await axios.get('/api/ai/settings', { withCredentials: true });
      // AI is enabled when ai_enabled is true (killswitch is OFF)
      setAiEnabled(response.data.ai_enabled === true || response.data.ai_enabled === 'true');
    } catch (error) {
      console.error('Error checking AI status:', error);
      // If AI settings endpoint fails, try to get from regular settings
      try {
        const settingsResponse = await axios.get('/api/settings', { withCredentials: true });
        // Check if ai_enabled exists in regular settings
        if (settingsResponse.data.ai_enabled !== undefined) {
          setAiEnabled(settingsResponse.data.ai_enabled === true || settingsResponse.data.ai_enabled === 'true');
        } else {
          // Default to enabled if not specified
          setAiEnabled(true);
        }
      } catch (settingsError) {
        console.error('Error checking settings:', settingsError);
        // Default to enabled if all checks fail
        setAiEnabled(true);
      }
    }
  };

  const handleSendMessage = async () => {
    if (!message.trim()) return;

    // Don't make API calls if we're logging out
    if (isLoggingOut || window.globalIsLoggingOut) {
      return;
    }

    setIsLoading(true);

    // Create Eastern time timestamp for optimistic updates
    const easternTime = new Date().toLocaleString('en-US', {
      timeZone: 'America/New_York'
    });
    const easternDate = new Date(easternTime);
    
    const dateStr = easternDate.toISOString().split('T')[0]; // YYYY-MM-DD format
    const timeStr = easternDate.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    }) + ' EST'; // Format: "10:48 PM EST"

    // Add user message immediately
    const userMessage = {
      id: Date.now(),
      date: dateStr,
      time: timeStr,
      prompt_type: 'manual',
      sender: 'user',
      body: message.trim(),
      conversation_id: conversationId,
      optimistic: true
    };

    // Insert placeholder AI message (Thinking…)
    const placeholderId = userMessage.id + 1;
    thinkingPlaceholderIdRef.current = placeholderId;
    const placeholderMessage = {
      id: placeholderId,
      date: dateStr,
      time: timeStr,
      prompt_type: 'manual',
      sender: 'agent',
      body: '',
      thinking: true,
      conversation_id: conversationId,
      optimistic: true
    };

    // Order with column-reverse: to appear visually as [user above, placeholder below],
    // we must insert in reverse order so that in reversed flex, user renders after placeholder.
    // Therefore push: [placeholder, user, ...prev]
    setConversations(prev => [placeholderMessage, userMessage, ...prev]);

    try {
      const response = await axios.post('/api/ai/conversation', {
        message: message.trim(),
        conversation_id: conversationId
      }, { withCredentials: true });

      // Replace placeholder with actual AI response
      setConversations(prev => prev.map(m =>
        m.id === placeholderId
          ? { ...m, body: response.data.response, thinking: false, optimistic: false }
          : (m.id === userMessage.id ? { ...m, optimistic: false } : m)
      ));
      setMessage('');
      setConversationId(response.data.conversation_id);
    } catch (error) {
      console.error('Error sending message:', error);
      // Show error in placeholder
      setConversations(prev => prev.map(m =>
        m.id === placeholderId ? { ...m, body: 'Error: Failed to get AI response.', thinking: false, optimistic: false } : m
      ));
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleSearch = () => {
    setOffset(0);
    setHasMore(true);
    fetchConversations(false);
  };

  const getPromptTypeIcon = (promptType) => {
    switch (promptType) {
      case 'market_analysis': return '📈';
      case 'risk_assessment': return '⚠️';
      case 'portfolio_review': return '💼';
      case 'news_analysis': return '📰';
      case 'sentiment_analysis': return '💭';
      case 'manual': return '💬';
      default: return '🤖';
    }
  };

  const getPromptTypeLabel = (promptType, sender) => {
    if (sender === 'user') return username || 'You';
    switch (promptType) {
      case 'market_analysis': return 'Market Analysis';
      case 'risk_assessment': return 'Risk Assessment';
      case 'portfolio_review': return 'Portfolio Review';
      case 'news_analysis': return 'News Analysis';
      case 'sentiment_analysis': return 'Sentiment Analysis';
      case 'manual': return 'AI';
      default: return 'AI';
    }
  };

  const formatTime = (timeStr) => {
    try {
      const date = new Date(timeStr);
      // Format as Eastern time with AM/PM
      return date.toLocaleTimeString('en-US', { 
        timeZone: 'America/New_York',
        hour: 'numeric', 
        minute: '2-digit',
        hour12: true
      });
    } catch (e) {
      console.error('Error formatting time:', e);
      return timeStr || '';
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    
    try {
      const date = new Date(dateStr + 'T00:00:00');
      const formattedDate = date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric'
      });
      
      // Return the formatted date with HTML entities encoded
      return formattedDate
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    } catch (e) {
      console.error('Error formatting date:', e);
      return dateStr || '';
    }
  };

  const normalizeAnchors = (input) => String(input || '').replace(
    /<a\s+[^>]*href=(["'])(.*?)\1[^>]*>(.*?)<\/a>/gi,
    (_, __, url, text) => `[${text}](${url})`
  );

  const linkify = (str) => {
    if (!str) return { __html: '' };
    
    let html = normalizeAnchors(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  
    // Handle markdown-style links [text](url)
    html = html.replace(
      /\[([^\]]+)\]\(((?:https?:\/\/)?[^\s)]+)\)/g, 
      (match, text, url) => {
        // Ensure URL has protocol
        const fullUrl = url.startsWith('http') ? url : `https://${url}`;
        return `<a href="${fullUrl}" target="_blank" rel="noopener noreferrer">${text}</a>`;
      }
    );
    
    // Handle plain URLs not in markdown format
    html = html.replace(
      /(^|\s)(https?:\/\/[^\s<]+[^<.,:;\"')\]\s])/g, 
      (match, space, url) => {
        // Truncate long URLs for display
        const displayUrl = url.length > 50 ? `${url.substring(0, 47)}...` : url;
        return `${space}<a href="${url}" target="_blank" rel="noopener noreferrer" title="${url}">${displayUrl}</a>`;
      }
    );
    
    // Convert newlines to <br> and multiple spaces to &nbsp;
    html = html
      .replace(/\n/g, '<br>')
      .replace(/ {2,}/g, ' &nbsp;');
      
    return { __html: html };
  };

  return (
    <div className={`ai-copilot-wrapper ${isOpen ? 'open' : ''}`} data-theme-wrapper>
      {/* Sidebar Toggle Button */}
      <div className="ai-copilot-toggle" onClick={() => setIsOpen(!isOpen)}>
        <div className="toggle-icon">🤖</div>
      </div>

      {/* AI Copilot Sidebar */}
      <div className="ai-copilot-sidebar">
        {/* ... existing component JSX ... */}
          <h3>🤖 AI Copilot</h3>
          <div className="header-controls">
            <label className="sentiment-toggle" title="Show only sentiment analysis messages">
              <input
                type="checkbox"
                checked={showSentiment}
                onChange={toggleSentimentFilter}
              />
              <span>Show Sentiment</span>
            </label>
            <label className="select-all-toggle" title="Select all messages">
              <input
                type="checkbox"
                checked={selectAll}
                onChange={toggleSelectAll}
              />
              <span>Select All</span>
            </label>
            {selectedMessages.size > 0 && (
              <div className="bulk-actions">
                <button 
                  className="btn btn-danger btn-sm"
                  onClick={bulkDelete}
                  title="Delete selected messages"
                >
                  Delete ({selectedMessages.size})
                </button>
                <button 
                  className="btn btn-success btn-sm"
                  onClick={bulkArchive}
                  title="Archive selected messages"
                >
                  Archive ({selectedMessages.size})
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Search and Filter Bar */}
        <div className="search-section">
          <div className="search-filter-container">
            <div className="search-input">
              <input
                type="text"
                placeholder="Search conversations..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
              />
              <button onClick={handleSearch} className="search-btn">
                🔍
              </button>
            </div>
            <div className="sentiment-filter">
              <label className="sentiment-toggle">
                <input
                  type="checkbox"
                  checked={showSentiment}
                  onChange={toggleSentimentFilter}
                />
                <span className="slider round"></span>
                <span className="sentiment-label">Show Sentiment</span>
              </label>
            </div>
          </div>
        </div>

        {/* Conversations */}
        <div className="conversations-container">
          <div className="conversations-list">
            
            {!aiEnabled && (
              <div className="ai-disabled-message">
                <div className="message-header">
                  <span className="prompt-type">
                    ⚠️ AI Disabled
                  </span>
                  <span className="message-time">
                    Now
                  </span>
                </div>
                <div className="message-body">
                  AI chatbot is currently disabled. Please enable AI in Settings to use this feature.
                </div>
              </div>
            )}
            {conversations.map((conv) => (
              <div key={conv.id} className={`conversation-message ${conv.sender}`}>
                <div className="message-header">
                  <div className="message-meta">
                    <input
                      type="checkbox"
                      checked={selectedMessages.has(conv.id)}
                      onChange={() => toggleSelectMessage(conv.id)}
                      className="message-checkbox"
                    />
                    <span className="prompt-type">
                      {getPromptTypeIcon(conv.prompt_type)} {getPromptTypeLabel(conv.prompt_type, conv.sender)}
                    </span>
                  </div>
                  <div className="message-time-actions">
                    <span className="message-datetime">
                      {formatDate(conv.date)} {conv.time}
                    </span>
                    <div className="message-actions">
                      <button
                        className="action-btn archive-btn"
                        onClick={() => archiveMessage(conv.id)}
                        title="Archive message"
                      >
                        📁
                      </button>
                      <button
                        className="action-btn delete-btn"
                        onClick={() => deleteMessage(conv.id)}
                        title="Delete message"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                </div>
                <div className="message-body">
                  {conv.thinking ? (
                    <em>Thinking{thinkingDots}</em>
                  ) : (
                    <div dangerouslySetInnerHTML={linkify(conv.body || '')} />
                  )}
                </div>
              </div>
            ))}
            
            {/* Load More Button - positioned at bottom/top when scrolled up */}
            {hasMore && conversations.length > 0 && (
              <div className="load-more-container">
                <button
                  className="load-more-btn"
                  onClick={loadMoreMessages}
                  disabled={isLoadingMore}
                >
                  {isLoadingMore ? '⏳ Loading...' : `📥 Load more messages (${totalCount - conversations.length} remaining)`}
                </button>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Message Input */}
        <div className="message-input-section">
          <div className="input-container">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={aiEnabled ? "Ask me anything about your portfolio or trading..." : "AI is disabled. Enable in Settings to chat."}
              rows={3}
              disabled={isLoading || !aiEnabled}
            />
            <button
              onClick={handleSendMessage}
              disabled={isLoading || !message.trim() || !aiEnabled}
              className="send-btn"
            >
              {isLoading ? '⏳' : aiEnabled ? '➤' : '🚫'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AICopilotSidebar;
