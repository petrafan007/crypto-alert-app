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
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const messagesEndRef = useRef(null);
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
  const [showAutomation, setShowAutomation] = useState(true);
  const [searchHits, setSearchHits] = useState([]);
  const [currentHitIndex, setCurrentHitIndex] = useState(-1);
  const messageRefs = useRef(new Map());
  const previousActiveHit = useRef(null);
  const limit = 20;

  const registerMessageRef = (id, node, isThinking = false) => {
    if (node && !isThinking) {
      messageRefs.current.set(id, node);
    } else {
      messageRefs.current.delete(id);
    }
  };

  const clearHighlights = () => {
    messageRefs.current.forEach((node) => {
      node.querySelectorAll('mark.search-highlight').forEach((mark) => {
        const textNode = document.createTextNode(mark.textContent);
        mark.replaceWith(textNode);
      });
      node.normalize();
    });
    if (previousActiveHit.current) {
      previousActiveHit.current.classList.remove('search-highlight-active');
      previousActiveHit.current = null;
    }
  };

  const highlightNode = (node, term) => {
    const hits = [];
    if (!term) return hits;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
    const lowerTerm = term.toLowerCase();
    const length = term.length;

    let textNode;
    while ((textNode = walker.nextNode())) {
      const text = textNode.nodeValue;
      if (!text) continue;
      const lowerText = text.toLowerCase();
      let matchIndex = lowerText.indexOf(lowerTerm);
      if (matchIndex === -1) continue;

      const fragment = document.createDocumentFragment();
      let lastIndex = 0;
      while (matchIndex !== -1) {
        if (matchIndex > lastIndex) {
          fragment.appendChild(document.createTextNode(text.slice(lastIndex, matchIndex)));
        }
        const mark = document.createElement('mark');
        mark.className = 'search-highlight';
        mark.textContent = text.slice(matchIndex, matchIndex + length);
        fragment.appendChild(mark);
        hits.push(mark);
        lastIndex = matchIndex + length;
        matchIndex = lowerText.indexOf(lowerTerm, lastIndex);
      }
      if (lastIndex < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
      }
      textNode.parentNode.replaceChild(fragment, textNode);
    }
    return hits;
  };

  // Load current username once
  useEffect(() => {
    (async () => {
      try {
        const r = await axios.get('/api/get-credentials', { withCredentials: true });
        if (r.data && r.data.username) setUsername(r.data.username);
      } catch { }
    })();
  }, []);

  // Check AI status and fetch conversations when sidebar opens
  useEffect(() => {
    if (isOpen) {
      checkAiStatus();
      fetchConversations(false, true); // Initial fetch when sidebar opens
      // Force scroll to bottom on open to show newest messages
      setTimeout(scrollToBottom, 100);
      setTimeout(scrollToBottom, 500); // Redundant safety for slow renders
    }
  }, [isOpen]);

  useEffect(() => {
    setOffset(0);
    setHasMore(true);
    if (isOpen) {
      fetchConversations(false, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAutomation]);

  // Background refresh DISABLED as per user request (only refresh on open)
  useEffect(() => {
    // Timer removed to prevent visual refreshing
    return () => { };
  }, []);

  useEffect(() => {
    clearHighlights();
    const term = activeSearchTerm.trim();
    if (!term) {
      setSearchHits([]);
      setCurrentHitIndex(-1);
      return;
    }

    const hits = [];
    messageRefs.current.forEach((node) => {
      const elements = highlightNode(node, term);
      elements.forEach((element) => {
        hits.push({ element });
      });
    });

    setSearchHits(hits);
    setCurrentHitIndex(hits.length ? 0 : -1);
  }, [activeSearchTerm, conversations]);

  useEffect(() => {
    if (!searchHits.length) {
      if (previousActiveHit.current) {
        previousActiveHit.current.classList.remove('search-highlight-active');
        previousActiveHit.current = null;
      }
      return;
    }

    let index = currentHitIndex;
    if (index < 0 || index >= searchHits.length) {
      index = 0;
    }

    const target = searchHits[index]?.element;
    if (!target) return;

    if (previousActiveHit.current && previousActiveHit.current !== target) {
      previousActiveHit.current.classList.remove('search-highlight-active');
    }

    target.classList.add('search-highlight-active');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    previousActiveHit.current = target;
  }, [currentHitIndex, searchHits]);
  // Animated dots for Thinking… placeholder while loading
  useEffect(() => {
    if (!isLoading) return;
    const iv = setInterval(() => {
      setThinkingDots(prev => (prev.length >= 3 ? '.' : prev + '.'));
    }, 500);
    return () => clearInterval(iv);
  }, [isLoading]);

  // Scroll to bottom when new messages arrive (only if not loading history)
  useEffect(() => {
    // Only scroll to bottom if we're not loading more history
    if (isLoadingMore) return;

    const conversationsContainer = document.querySelector('.conversations-list');
    if (conversationsContainer) {
      scrollToBottom();
    }
  }, [conversations]); // Note: isLoadingMore ref dependency handled by return guard

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'auto' }); // Instant scroll, no smooth animation
  };

  const fetchConversations = async (loadMore = false, force = false) => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) return;

      if (loadMore) {
        setIsLoadingMore(true);
      }

      const currentOffset = (loadMore && !force) ? offset : 0;

      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      params.append('offset', currentOffset.toString());
      params.append('include_hidden', 'false');
      if (!showAutomation) {
        params.append('prompt_type', 'manual');
      }

      const response = await axios.get(`/api/ai/conversations?${params}`, {
        withCredentials: true
      });

      const fetched = response.data.conversations || [];
      const total = response.data.total || 0;
      const hasMoreData = response.data.has_more || false;
      const signatureKey = (entry) => `${entry.sender}|${(entry.body || '').trim()}`;
      const serverSignatures = new Set(fetched.map(signatureKey));

      setTotalCount(total);
      setHasMore(hasMoreData);

      if (force) {
        // Initial load: keep any optimistic messages (e.g., in-flight Thinking…)
        setConversations(prev => {
          const optimistic = prev.filter(m => m.optimistic);
          const fetchedSorted = [...fetched].reverse(); // Newest...Oldest -> Oldest...Newest
          const merged = new Map();
          [...fetchedSorted, ...optimistic].forEach(m => merged.set(m.id, m));
          const ordered = Array.from(merged.values()).sort((a, b) => (a.id || 0) - (b.id || 0));
          return ordered;
        });
        setOffset(fetched.length);
      } else if (loadMore) {
        // Loading older history
        setConversations(prev => {
          const existingIds = new Set(prev.map(m => m.id));
          const additions = fetched.filter(conv => !existingIds.has(conv.id));

          if (!additions.length) return prev;

          // additions is [Older ... Oldest]
          // reverse to [Oldest ... Older]
          const olderMessages = [...additions].reverse();

          return [...olderMessages, ...prev];
        });
        setOffset(currentOffset + fetched.length);
      } else {
        // Manual update/fallback
        setConversations(prev => {
          // Simple merge logic: combine and sort by ID
          const combined = [...prev, ...fetched];
          // Deduplicate by ID
          const unique = Array.from(new Map(combined.map(item => [item.id, item])).values());
          // Sort ID Ascending (Oldest -> Newest)
          unique.sort((a, b) => (a.id || 0) - (b.id || 0));
          return unique;
        });
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

    const easternNow = new Date();

    const dateParts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    }).formatToParts(easternNow);

    const month = dateParts.find((part) => part.type === 'month')?.value || '01';
    const day = dateParts.find((part) => part.type === 'day')?.value || '01';
    const year = dateParts.find((part) => part.type === 'year')?.value || String(easternNow.getUTCFullYear());
    const dateStr = `${year}-${month}-${day}`;

    const timeStr = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    }).format(easternNow);

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

      const newConversationId = response.data.conversation_id;

      // Replace placeholder with actual AI response and attach conversation id
      setConversations(prev => prev.map((m) => {
        if (m.id === placeholderId) {
          return {
            ...m,
            body: response.data.response,
            thinking: false,
            optimistic: false,
            conversation_id: newConversationId
          };
        }
        if (m.id === userMessage.id) {
          return {
            ...m,
            optimistic: false,
            conversation_id: newConversationId
          };
        }
        return m;
      }));
      setMessage('');
      setConversationId(newConversationId);
    } catch (error) {
      console.error('Error sending message:', error);
      // Show error in placeholder
      setConversations(prev => prev.map(m =>
        m.id === placeholderId ? { ...m, body: 'Error: Failed to get AI response.', thinking: false, optimistic: false } : m
      ));
      // Clear input so it doesn't feel stuck
      setMessage('');
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
    setActiveSearchTerm(searchTerm.trim());
  };

  const clearSearch = () => {
    clearHighlights();
    setSearchTerm('');
    setActiveSearchTerm('');
    setSearchHits([]);
    setCurrentHitIndex(-1);
  };

  const goToNextHit = () => {
    if (!searchHits.length) return;
    setCurrentHitIndex((prev) => {
      if (prev === -1) return 0;
      return (prev + 1) % searchHits.length;
    });
  };

  const goToPreviousHit = () => {
    if (!searchHits.length) return;
    setCurrentHitIndex((prev) => {
      if (prev === -1) return searchHits.length - 1;
      return (prev - 1 + searchHits.length) % searchHits.length;
    });
  };

  const getPromptTypeIcon = (promptType) => {
    switch (promptType) {
      case 'market_analysis': return '📈';
      case 'risk_assessment': return '⚠️';
      case 'portfolio_review': return '💼';
      case 'news_analysis': return '📰';
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
    } catch {
      return timeStr;
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    try {
      // Handle YYYY-MM-DD format
      const date = new Date(`${dateStr}T12:00:00`);
      if (Number.isNaN(date.getTime())) {
        throw new Error('Invalid date');
      }
      return date.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric'
      });
    } catch {
      // Fallback for other formats
      return dateStr;
    }
  };

  // Combined date+time formatter for display: "Sat, Oct 18, 2025 at 5:23 PM EST"
  const formatDateTime = (dateStr, timeStr) => {
    if (!dateStr) return timeStr || '';
    const formattedDate = formatDate(dateStr);
    if (!timeStr) return formattedDate;
    // Remove redundant "EST" suffix handling, time already includes it
    return `${formattedDate} at ${timeStr}`;
  };

  // Safely render text with clickable links, preserving newlines
  const normalizeAnchors = (str) => str.replace(
    /<a\s+[^>]*href=(["'])(.*?)\1[^>]*>(.*?)<\/a>/gi,
    (_, __, url, text) => `[${text}](${url})`
  );

  const escapeHtml = (str) => str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  const linkify = (str) => {
    let html = escapeHtml(normalizeAnchors(str));

    const buildLink = (rawUrl, label) => {
      const normalizedUrl = rawUrl.startsWith('http') ? rawUrl : `https:${rawUrl}`;
      const safeLabel = label || rawUrl;
      return `<a href="${normalizedUrl}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`;
    };

    // Markdown-style [text](url) links, allowing protocol-relative URLs
    html = html.replace(/\[([^\]]+)\]\(((?:https?:)?\/\/[^)\s]+)\)/g, (_, text, url) => buildLink(url, text));

    // Plain URLs including protocol-relative variants
    html = html.replace(/((?:https?:)?\/\/[^\s)\]]+)/g, (match) => buildLink(match));

    // Newlines to <br>
    html = html.replace(/\n/g, '<br/>');
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
        <div className="sidebar-header">
          <h3>🤖 AI Copilot</h3>
          <div className="header-controls">
            <label className="auto-refresh-toggle">
              <input
                type="checkbox"
                checked={showAutomation}
                onChange={(e) => setShowAutomation(e.target.checked)}
              />
              <span>Show workflows</span>
            </label>
            <label className="select-all-toggle">
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

        {/* Search Bar */}
        <div className="search-section">
          <div className="search-input">
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSearch();
                }
              }}
            />
            <button onClick={handleSearch} className="search-btn">
              🔍
            </button>
          </div>
          {activeSearchTerm && (
            <div className="search-status">
              <span>
                {searchHits.length
                  ? `Result ${currentHitIndex >= 0 ? currentHitIndex + 1 : 0} of ${searchHits.length}`
                  : 'No results found'}
              </span>
              <div className="search-controls">
                <button onClick={goToPreviousHit} disabled={!searchHits.length} title="Previous match">
                  ↑
                </button>
                <button onClick={goToNextHit} disabled={!searchHits.length} title="Next match">
                  ↓
                </button>
                <button onClick={clearSearch} title="Clear search">
                  ✖
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Conversations */}
        <div className="conversations-container">
          <div className="conversations-list">

            {/* Load More Button - positioned at top for history */}
            {hasMore && conversations.length > 0 && (
              <div className="load-more-container">
                <button
                  className="load-more-btn"
                  onClick={loadMoreMessages}
                  disabled={isLoadingMore}
                >
                  {isLoadingMore ? '⏳ Loading...' : `📥 Load older messages (${Math.max(totalCount - conversations.length, 0)} remaining)`}
                </button>
              </div>
            )}

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
                  You need to add your AI integration information in settings to use the AI Copilot
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
                      {formatDateTime(conv.date, conv.time)}
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
                <div
                  className="message-body"
                  ref={(node) => registerMessageRef(conv.id, node, conv.thinking)}
                >
                  {conv.thinking ? (
                    <em>Thinking{thinkingDots}</em>
                  ) : (
                    <div dangerouslySetInnerHTML={linkify(conv.body || '')} />
                  )}
                </div>
              </div>
            ))}



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
