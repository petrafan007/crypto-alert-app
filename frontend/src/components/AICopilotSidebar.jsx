import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import './AICopilotSidebar.css';
import { useAuth } from './AuthContext';

const COPILOT_MARKDOWN_SCHEMA = {
  ...defaultSchema,
  tagNames: [...new Set([...(defaultSchema.tagNames || []), 'u', 's', 'del', 'mark', 'kbd'])],
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes.a || []), 'target', 'rel'],
    img: [...(defaultSchema.attributes.img || []), 'src', 'alt', 'title', 'width', 'height']
  }
};

const FLOATING_WINDOW_STATE_KEY = 'ai_copilot_floating_window_state_v1';
const FLOATING_WINDOW_MIN_WIDTH = 380;
const FLOATING_WINDOW_MIN_HEIGHT = 420;
const FLOATING_WINDOW_INSET = 12;

const readFloatingWindowState = () => {
  const fallback = { minimized: false, maximized: false, position: null, size: null };
  if (typeof window === 'undefined') return fallback;

  try {
    const saved = JSON.parse(window.localStorage.getItem(FLOATING_WINDOW_STATE_KEY) || 'null');
    if (!saved || typeof saved !== 'object') return fallback;

    const isFiniteNumber = (value) => Number.isFinite(value);
    const position = isFiniteNumber(saved.position?.left) && isFiniteNumber(saved.position?.top)
      ? { left: saved.position.left, top: saved.position.top }
      : null;
    const size = isFiniteNumber(saved.size?.width) && isFiniteNumber(saved.size?.height)
      ? { width: saved.size.width, height: saved.size.height }
      : null;

    return {
      minimized: Boolean(saved.minimized),
      maximized: Boolean(saved.maximized),
      position,
      size
    };
  } catch {
    return fallback;
  }
};

export default function AICopilotSidebar() {
  const { isLoggingOut } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [isFloating, setIsFloating] = useState(false);
  const [isMaximized, setIsMaximized] = useState(() => readFloatingWindowState().maximized);
  const [isMinimized, setIsMinimized] = useState(() => readFloatingWindowState().minimized);
  const [floatingPosition, setFloatingPosition] = useState(() => readFloatingWindowState().position);
  const [floatingSize, setFloatingSize] = useState(() => readFloatingWindowState().size);
  const [conversations, setConversations] = useState([]);
  const [message, setMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [includeAllSessions, setIncludeAllSessions] = useState(false);
  const floatingWindowRef = useRef(null);
  const floatingDragRef = useRef(null);
  const floatingResizeRef = useRef(null);
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
  const [searchHits, setSearchHits] = useState([]);
  const [currentHitIndex, setCurrentHitIndex] = useState(-1);
  const messageRefs = useRef(new Map());
  const conversationRefs = useRef(new Map());
  const activeSessionIdRef = useRef(null);
  const previousActiveHit = useRef(null);
  const limit = 20;

  useEffect(() => {
    if (typeof window === 'undefined') return;

    window.localStorage.setItem(FLOATING_WINDOW_STATE_KEY, JSON.stringify({
      minimized: isMinimized,
      maximized: isMaximized,
      position: floatingPosition,
      size: floatingSize
    }));
  }, [floatingPosition, floatingSize, isMaximized, isMinimized]);

  const registerMessageRef = (id, node, isThinking = false) => {
    if (node && !isThinking) {
      messageRefs.current.set(id, node);
    } else {
      messageRefs.current.delete(id);
    }
  };

  const registerConversationRef = (id, node) => {
    if (node) {
      conversationRefs.current.set(id, node);
    } else {
      conversationRefs.current.delete(id);
    }
  };

  const scrollToResponseStart = (questionId) => {
    const question = conversationRefs.current.get(questionId);
    question?.scrollIntoView({ behavior: 'auto', block: 'start' });
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

  useEffect(() => {
    activeSessionIdRef.current = conversationId;
  }, [conversationId]);

  // Load the user's saved chat sessions when either Copilot presentation opens.
  useEffect(() => {
    if (isOpen || isFloating) {
      checkAiStatus();
      fetchSessions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, isFloating]);

  useEffect(() => {
    setOffset(0);
    setHasMore(true);
    if ((isOpen || isFloating) && conversationId) {
      fetchConversations(false, true);
    } else if (isOpen || isFloating) {
      setConversations([]);
      setTotalCount(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, isOpen, isFloating]);

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

  const openFloatingWindow = () => {
    setIsOpen(false);
    setIsFloating(true);
    setIsMinimized(false);
  };

  const closeFloatingWindow = () => {
    setIsFloating(false);
    setIsMaximized(false);
    setIsMinimized(false);
    setIsOpen(false);
  };

  const captureFloatingWindowBounds = () => {
    const windowElement = floatingWindowRef.current;
    if (!windowElement) return null;

    const rect = windowElement.getBoundingClientRect();
    const bounds = {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height
    };
    setFloatingPosition({ left: bounds.left, top: bounds.top });
    setFloatingSize({ width: bounds.width, height: bounds.height });
    return bounds;
  };

  const minimizeFloatingWindow = () => {
    if (!isMaximized) captureFloatingWindowBounds();
    setIsMinimized(true);
    setIsFloating(false);
    setIsOpen(false);
  };

  const restoreMinimizedWindow = () => {
    setIsMinimized(false);
    setIsOpen(false);
    setIsFloating(true);
  };

  const handleFloatingDragStart = (event) => {
    if (isMaximized || event.button !== 0 || event.target.closest('button')) return;

    const bounds = captureFloatingWindowBounds();
    if (!bounds) return;

    floatingDragRef.current = {
      offsetX: event.clientX - bounds.left,
      offsetY: event.clientY - bounds.top
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handleFloatingDragMove = (event) => {
    const drag = floatingDragRef.current;
    const windowElement = floatingWindowRef.current;
    if (!drag || !windowElement) return;

    const rect = windowElement.getBoundingClientRect();
    const maxLeft = Math.max(FLOATING_WINDOW_INSET, window.innerWidth - rect.width - FLOATING_WINDOW_INSET);
    const maxTop = Math.max(FLOATING_WINDOW_INSET, window.innerHeight - rect.height - FLOATING_WINDOW_INSET);
    const left = Math.min(maxLeft, Math.max(FLOATING_WINDOW_INSET, event.clientX - drag.offsetX));
    const top = Math.min(maxTop, Math.max(FLOATING_WINDOW_INSET, event.clientY - drag.offsetY));
    setFloatingPosition({ left, top });
  };

  const handleFloatingDragEnd = (event) => {
    floatingDragRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleFloatingResizeStart = (event, direction) => {
    if (isMaximized || event.button !== 0) return;

    event.preventDefault();
    event.stopPropagation();
    const bounds = captureFloatingWindowBounds();
    if (!bounds) return;

    floatingResizeRef.current = {
      ...bounds,
      direction,
      startX: event.clientX,
      startY: event.clientY
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handleFloatingResizeMove = (event) => {
    const resize = floatingResizeRef.current;
    if (!resize) return;

    const minWidth = Math.min(FLOATING_WINDOW_MIN_WIDTH, window.innerWidth - (FLOATING_WINDOW_INSET * 2));
    const minHeight = Math.min(FLOATING_WINDOW_MIN_HEIGHT, window.innerHeight - (FLOATING_WINDOW_INSET * 2));
    const right = resize.left + resize.width;
    const bottom = resize.top + resize.height;
    const deltaX = event.clientX - resize.startX;
    const deltaY = event.clientY - resize.startY;
    let { left, top, width, height } = resize;

    if (resize.direction.includes('e')) {
      width = Math.max(minWidth, Math.min(window.innerWidth - FLOATING_WINDOW_INSET - left, resize.width + deltaX));
    }
    if (resize.direction.includes('w')) {
      width = Math.max(minWidth, Math.min(right - FLOATING_WINDOW_INSET, resize.width - deltaX));
      left = right - width;
    }
    if (resize.direction.includes('s')) {
      height = Math.max(minHeight, Math.min(window.innerHeight - FLOATING_WINDOW_INSET - top, resize.height + deltaY));
    }
    if (resize.direction.includes('n')) {
      height = Math.max(minHeight, Math.min(bottom - FLOATING_WINDOW_INSET, resize.height - deltaY));
      top = bottom - height;
    }

    setFloatingPosition({ left, top });
    setFloatingSize({ width, height });
  };

  const handleFloatingResizeEnd = (event) => {
    floatingResizeRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const toggleFloatingMaximize = () => {
    if (!isMaximized) captureFloatingWindowBounds();
    setIsMaximized((maximized) => !maximized);
  };

  const fetchSessions = async () => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) return;
      const response = await axios.get('/api/ai/copilot-sessions', { withCredentials: true });
      const loadedSessions = response.data?.sessions || [];
      setSessions(loadedSessions);
      setConversationId((currentSessionId) => (
        currentSessionId && loadedSessions.some((session) => session.id === currentSessionId)
          ? currentSessionId
          : (loadedSessions[0]?.id || null)
      ));
    } catch (error) {
      console.error('Error fetching Copilot sessions:', error);
    }
  };

  const createSession = async () => {
    setIsCreatingSession(true);
    try {
      const response = await axios.post('/api/ai/copilot-sessions', {}, { withCredentials: true });
      const newSession = response.data?.session;
      if (!newSession?.id) throw new Error('The new Copilot session was not created.');
      setSessions((previous) => [newSession, ...previous.filter((session) => session.id !== newSession.id)]);
      setConversationId(newSession.id);
      setConversations([]);
      setSelectedMessages(new Set());
      setOffset(0);
      setTotalCount(0);
      setHasMore(false);
      return newSession.id;
    } catch (error) {
      console.error('Error creating Copilot session:', error);
      return null;
    } finally {
      setIsCreatingSession(false);
    }
  };

  const handleNewChat = () => {
    if (!isCreatingSession && !isLoading) createSession();
  };

  const handleSessionChange = (event) => {
    const nextSessionId = event.target.value || null;
    setConversationId(nextSessionId);
    setConversations([]);
    setSelectedMessages(new Set());
    setOffset(0);
    setTotalCount(0);
    setHasMore(true);
  };

  const fetchConversations = async (loadMore = false, force = false, requestedSessionId = conversationId) => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut || !requestedSessionId) return;

      if (loadMore) {
        setIsLoadingMore(true);
      }

      const currentOffset = (loadMore && !force) ? offset : 0;

      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      params.append('offset', currentOffset.toString());
      params.append('include_hidden', 'false');
      params.append('prompt_type', 'manual');
      params.append('session_id', requestedSessionId);

      const response = await axios.get(`/api/ai/conversations?${params}`, {
        withCredentials: true
      });

      const fetched = response.data.conversations || [];
      const total = response.data.total || 0;
      const hasMoreData = response.data.has_more || false;
      if (activeSessionIdRef.current !== requestedSessionId) return;

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
    // 1. Instantly remove from UI optimistically
    setConversations(prev => prev.filter(conv => String(conv.id) !== String(messageId)));
    setSelectedMessages(prev => {
      const next = new Set(prev);
      next.delete(messageId);
      next.delete(Number(messageId));
      next.delete(String(messageId));
      return next;
    });
    setTotalCount(prev => Math.max(0, prev - 1));

    // 2. Perform backend deletion in background if it's a persisted DB record
    if (typeof messageId === 'number' || (!String(messageId).startsWith('optimistic_') && !String(messageId).startsWith('placeholder_') && !isNaN(Number(messageId)))) {
      try {
        await axios.delete(`/api/ai/conversations/${messageId}`, {
          withCredentials: true
        });
      } catch (error) {
        console.error('Error deleting message:', error);
      }
    }
  };

  const archiveMessage = async (messageId) => {
    // 1. Instantly remove from UI optimistically
    setConversations(prev => prev.filter(conv => String(conv.id) !== String(messageId)));
    setSelectedMessages(prev => {
      const next = new Set(prev);
      next.delete(messageId);
      next.delete(Number(messageId));
      next.delete(String(messageId));
      return next;
    });
    setTotalCount(prev => Math.max(0, prev - 1));

    // 2. Perform backend archive in background if it's a persisted DB record
    if (typeof messageId === 'number' || (!String(messageId).startsWith('optimistic_') && !String(messageId).startsWith('placeholder_') && !isNaN(Number(messageId)))) {
      try {
        await axios.patch(`/api/ai/conversations/${messageId}/archive`, {}, {
          withCredentials: true
        });
      } catch (error) {
        console.error('Error archiving message:', error);
      }
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

    const idsToDelete = new Set(Array.from(selectedMessages).map(id => String(id)));
    const idsArray = Array.from(selectedMessages);

    // 1. Instantly remove from UI optimistically
    setConversations(prev => prev.filter(conv => !idsToDelete.has(String(conv.id))));
    setTotalCount(prev => Math.max(0, prev - idsArray.length));
    setSelectedMessages(new Set());
    setSelectAll(false);

    // 2. Perform backend deletion in background
    try {
      await Promise.all(
        idsArray.filter(id => typeof id === 'number' || !isNaN(Number(id))).map(id =>
          axios.delete(`/api/ai/conversations/${id}`, { withCredentials: true })
        )
      );
    } catch (error) {
      console.error('Error bulk deleting messages:', error);
    }
  };

  const bulkArchive = async () => {
    if (selectedMessages.size === 0) return;

    const idsToArchive = new Set(Array.from(selectedMessages).map(id => String(id)));
    const idsArray = Array.from(selectedMessages);

    // 1. Instantly remove from UI optimistically
    setConversations(prev => prev.filter(conv => !idsToArchive.has(String(conv.id))));
    setTotalCount(prev => Math.max(0, prev - idsArray.length));
    setSelectedMessages(new Set());
    setSelectAll(false);

    // 2. Perform backend archive in background
    try {
      await Promise.all(
        idsArray.filter(id => typeof id === 'number' || !isNaN(Number(id))).map(id =>
          axios.patch(`/api/ai/conversations/${id}/archive`, {}, { withCredentials: true })
        )
      );
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
    const activeConversationId = conversationId || await createSession();
    if (!activeConversationId) {
      setIsLoading(false);
      return;
    }

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
      conversation_id: activeConversationId,
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
      sender: 'ai',
      body: '',
      thinking: true,
      conversation_id: activeConversationId,
      optimistic: true
    };

    // Append to end of conversation list (Oldest -> Newest order)
    setConversations(prev => [...prev, userMessage, placeholderMessage]);
    setMessage('');
    window.setTimeout(() => scrollToResponseStart(userMessage.id), 0);

    try {
      const response = await axios.post('/api/ai/conversation', {
        message: userMessage.body,
        conversation_id: activeConversationId,
        include_all_sessions: includeAllSessions,
      }, {
        withCredentials: true,
        timeout: 120000
      });

      const newConversationId = response.data?.conversation_id;
      const aiResponseText = response.data?.response || 'No response generated.';
      const updatedSession = response.data?.session;

      if (updatedSession?.id) {
        setSessions((previous) => [
          updatedSession,
          ...previous.filter((session) => session.id !== updatedSession.id),
        ]);
      }

      if (activeSessionIdRef.current !== activeConversationId) return;

      // Replace placeholder with actual AI response and attach conversation id
      setConversations(prev => prev.map((m) => {
        if (m.id === placeholderId) {
          return {
            ...m,
            body: aiResponseText,
            thinking: false,
            optimistic: false,
            conversation_id: newConversationId,
            tier: response.data?.tier,
            provider: response.data?.provider,
            model: response.data?.model
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
      setConversationId(newConversationId);
      window.setTimeout(() => scrollToResponseStart(userMessage.id), 0);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMsg = error.response?.data?.response || error.response?.data?.error || (error.code === 'ECONNABORTED' ? 'Request timed out. Please try again.' : 'Error: Failed to get AI response. Please try again.');
      if (activeSessionIdRef.current !== activeConversationId) return;
      // Show error in placeholder
      setConversations(prev => prev.map(m =>
        m.id === placeholderId ? { ...m, body: errorMsg, thinking: false, optimistic: false } : m
      ));
      window.setTimeout(() => scrollToResponseStart(userMessage.id), 0);
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
      case 'risk_assessment':
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
      case 'risk_assessment':
      case 'portfolio_review': return 'Portfolio Review';
      case 'news_analysis': return 'News Analysis';
      case 'manual': return 'AI';
      default: return 'AI';
    }
  };

  const getProviderLabel = (provider) => {
    switch ((provider || '').toLowerCase()) {
      case 'openai': return 'OpenAI';
      case 'gemini': return 'Google Gemini';
      case 'zai': return 'Z.AI';
      case 'perplexity': return 'Perplexity';
      case 'inception': return 'Inception Labs';
      default: return provider || 'AI';
    }
  };

  const getTierLabel = (tier) => {
    if (!tier) return 'Primary';
    return tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase();
  };

  const getAiTooltip = (conv) => {
    if (conv.sender !== 'ai') return '';
    const tier = getTierLabel(conv.tier);
    const provider = getProviderLabel(conv.provider || 'openai');
    const model = conv.model || 'Default';
    return `Tier: ${tier}\nProvider: ${provider}\nModel: ${model}`;
  };

  // Combined date+time formatter for display: "8-20-2026 at 5:50 PM EDT"
  const formatEasternDateTime = (dateStr, timeStr, createdAt) => {
    try {
      let d = null;
      if (createdAt) {
        d = new Date(createdAt);
      } else if (dateStr && timeStr) {
        if (dateStr.includes('GMT') || dateStr.includes('UTC')) {
          const parsedDate = new Date(dateStr);
          if (!isNaN(parsedDate.getTime())) {
            const timeParts = timeStr.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?/);
            if (timeParts) {
              const hours = parseInt(timeParts[1], 10);
              const minutes = parseInt(timeParts[2], 10);
              const seconds = timeParts[3] ? parseInt(timeParts[3], 10) : 0;
              d = new Date(Date.UTC(parsedDate.getUTCFullYear(), parsedDate.getUTCMonth(), parsedDate.getUTCDate(), hours, minutes, seconds));
            } else {
              d = parsedDate;
            }
          }
        } else if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr.trim())) {
          const [y, m, day] = dateStr.trim().split('-').map(Number);
          const timeParts = (timeStr || '').match(/(\d{1,2}):(\d{2})(?::(\d{2}))?/);
          if (timeParts) {
            const hours = parseInt(timeParts[1], 10);
            const minutes = parseInt(timeParts[2], 10);
            const seconds = timeParts[3] ? parseInt(timeParts[3], 10) : 0;
            d = new Date(Date.UTC(y, m - 1, day, hours, minutes, seconds));
          } else {
            d = new Date(y, m - 1, day);
          }
        } else {
          const parsed = new Date(`${dateStr} ${timeStr}`);
          if (!isNaN(parsed.getTime())) d = parsed;
        }
      }

      if (d && !isNaN(d.getTime())) {
        const formatter = new Intl.DateTimeFormat('en-US', {
          timeZone: 'America/New_York',
          year: 'numeric',
          month: 'numeric',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
          hour12: true,
          timeZoneName: 'short'
        });
        const parts = formatter.formatToParts(d);
        const getPart = (type) => parts.find(p => p.type === type)?.value || '';
        const month = getPart('month');
        const day = getPart('day');
        const year = getPart('year');
        const hour = getPart('hour');
        const minute = getPart('minute');
        const dayPeriod = getPart('dayPeriod');
        const timeZoneName = getPart('timeZoneName') || 'EDT';
        return `${month}-${day}-${year} at ${hour}:${minute} ${dayPeriod} ${timeZoneName}`;
      }
    } catch (e) {
      console.warn('Error formatting date time:', e);
    }

    const cleanDate = (dateStr || '').replace(/\s*00:00:00\s*GMT/gi, '').replace(/^[A-Za-z]+,\s*/, '');
    return `${cleanDate} at ${timeStr || ''}`.trim();
  };

  const renderCopilotContent = (showSidebarTitle = true) => (
    <>
      <div className="sidebar-header">
        {showSidebarTitle && (
          <div className="copilot-title-row">
            <h3>🤖 AI Copilot</h3>
            <button
              type="button"
              className="copilot-window-btn"
              onClick={openFloatingWindow}
              title="Open AI Copilot in a floating window"
              aria-label="Open AI Copilot in a floating window"
            >
              ⧉
            </button>
          </div>
        )}
        <div className="header-controls">
          <div className="copilot-session-controls">
            <button
              type="button"
              className="new-copilot-chat-btn"
              onClick={handleNewChat}
              disabled={isCreatingSession || isLoading}
            >
              {isCreatingSession ? 'Creating…' : '+ New Chat'}
            </button>
            <select
              value={conversationId || ''}
              onChange={handleSessionChange}
              disabled={isCreatingSession || isLoading}
              aria-label="Choose a saved Copilot chat session"
            >
              <option value="">Choose a chat session</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.id}>
                  {session.title || 'Untitled chat'}{session.message_count ? ` (${session.message_count})` : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="checkbox-row" style={{ display: 'flex', gap: '15px' }}>
            <label className="auto-refresh-toggle" title="Explicitly search your other saved Copilot chats for related history">
              <input type="checkbox" checked={includeAllSessions} onChange={(e) => setIncludeAllSessions(e.target.checked)} />
              <span>Reference past chats</span>
            </label>
            <label className="select-all-toggle">
              <input type="checkbox" checked={selectAll} onChange={toggleSelectAll} />
              <span>Select All</span>
            </label>
          </div>
          {selectedMessages.size > 0 && (
            <div className="bulk-actions">
              <button className="btn btn-danger btn-sm" onClick={bulkDelete} title="Delete selected messages">
                Delete ({selectedMessages.size})
              </button>
              <button className="btn btn-success btn-sm" onClick={bulkArchive} title="Archive selected messages">
                Archive ({selectedMessages.size})
              </button>
            </div>
          )}
        </div>
      </div>

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
          <button onClick={handleSearch} className="search-btn" aria-label="Search conversations">🔍</button>
        </div>
        {activeSearchTerm && (
          <div className="search-status">
            <span>{searchHits.length ? `Result ${currentHitIndex >= 0 ? currentHitIndex + 1 : 0} of ${searchHits.length}` : 'No results found'}</span>
            <div className="search-controls">
              <button onClick={goToPreviousHit} disabled={!searchHits.length} title="Previous match">↑</button>
              <button onClick={goToNextHit} disabled={!searchHits.length} title="Next match">↓</button>
              <button onClick={clearSearch} title="Clear search">✖</button>
            </div>
          </div>
        )}
      </div>

      <div className="conversations-container">
        <div className="conversations-list">
          {hasMore && conversations.length > 0 && (
            <div className="load-more-container">
              <button className="load-more-btn" onClick={loadMoreMessages} disabled={isLoadingMore}>
                {isLoadingMore ? '⏳ Loading...' : `📥 Load older messages (${Math.max(totalCount - conversations.length, 0)} remaining)`}
              </button>
            </div>
          )}

          {!aiEnabled && (
            <div className="ai-disabled-message">
              <div className="message-header"><span className="prompt-type">⚠️ AI Disabled</span><span className="message-time">Now</span></div>
              <div className="message-body">You need to add your AI integration information in settings to use the AI Copilot</div>
            </div>
          )}

          {conversations.map((conv) => (
            <div
              key={conv.id}
              ref={(node) => registerConversationRef(conv.id, node)}
              className={`conversation-message ${conv.sender}`}
            >
              <div className="message-header">
                <div className="message-meta">
                  <input type="checkbox" checked={selectedMessages.has(conv.id)} onChange={() => toggleSelectMessage(conv.id)} className="message-checkbox" />
                  <span className="prompt-type" title={getAiTooltip(conv)} style={conv.sender === 'ai' ? { cursor: 'help' } : {}}>
                    {getPromptTypeIcon(conv.prompt_type)} {getPromptTypeLabel(conv.prompt_type, conv.sender)}
                  </span>
                </div>
                <div className="message-time-actions">
                  <span className="message-datetime">{formatEasternDateTime(conv.date, conv.time, conv.created_at)}</span>
                  <div className="message-actions">
                    <button className="action-btn archive-btn" onClick={() => archiveMessage(conv.id)} title="Archive message">📁</button>
                    <button className="action-btn delete-btn" onClick={() => deleteMessage(conv.id)} title="Delete message">🗑️</button>
                  </div>
                </div>
              </div>
              <div className="message-body rich-message-body" ref={(node) => registerMessageRef(conv.id, node, conv.thinking)}>
                {conv.thinking ? (
                  <em>Thinking{thinkingDots}</em>
                ) : (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw, [rehypeSanitize, COPILOT_MARKDOWN_SCHEMA]]}
                    components={{
                      a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                      img: ({ node, ...props }) => <img {...props} loading="lazy" />
                    }}
                  >
                    {conv.body || ''}
                  </ReactMarkdown>
                )}
              </div>
            </div>
          ))}
          {!conversationId && !conversations.length && (
            <div className="copilot-empty-session">Start a new chat to ask the Copilot a question.</div>
          )}
        </div>
      </div>

      <div className="message-input-section">
        <div className="input-container">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={aiEnabled ? 'Ask me anything about your portfolio or trading...' : 'AI is disabled. Enable in Settings to chat.'}
            rows={3}
            disabled={isLoading || !aiEnabled}
          />
          <button onClick={handleSendMessage} disabled={isLoading || !message.trim() || !aiEnabled} className="send-btn">
            {isLoading ? '⏳' : aiEnabled ? '➤' : '🚫'}
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className={`ai-copilot-wrapper ${isOpen && !isFloating ? 'open' : ''} ${isFloating ? 'floating-open' : ''}`} data-theme-wrapper>
      {!isFloating && !isMinimized && (
        <button type="button" className="ai-copilot-toggle" onClick={() => setIsOpen((open) => !open)} aria-label="Toggle AI Copilot">
          <span className="toggle-icon">🤖</span>
        </button>
      )}

      {isMinimized && (
        <button type="button" className="ai-copilot-minimized-tab" onClick={restoreMinimizedWindow} title="Restore AI Copilot" aria-label="Restore minimized AI Copilot">
          <span aria-hidden="true">🤖</span>
          <span>AI Copilot</span>
        </button>
      )}

      <aside className="ai-copilot-sidebar" aria-hidden={!isOpen || isFloating || isMinimized}>
        {!isFloating && renderCopilotContent(true)}
      </aside>

      {isFloating && (
        <section
          ref={floatingWindowRef}
          className={`ai-copilot-floating-window ${isMaximized ? 'maximized' : ''}`}
          style={!isMaximized && floatingPosition ? {
            left: `${floatingPosition.left}px`,
            top: `${floatingPosition.top}px`,
            right: 'auto',
            ...(floatingSize ? { width: `${floatingSize.width}px`, height: `${floatingSize.height}px` } : {})
          } : undefined}
          role="dialog"
          aria-label="AI Copilot floating chat window"
        >
          <div
            className={`floating-window-titlebar ${isMaximized ? 'maximized' : ''}`}
            onPointerDown={handleFloatingDragStart}
            onPointerMove={handleFloatingDragMove}
            onPointerUp={handleFloatingDragEnd}
            onPointerCancel={handleFloatingDragEnd}
            title={isMaximized ? undefined : 'Drag to move the AI Copilot window'}
          >
            <span>🤖 AI Copilot</span>
            <div className="floating-window-actions">
              <button type="button" onClick={minimizeFloatingWindow} title="Minimize AI Copilot" aria-label="Minimize AI Copilot">—</button>
              <button type="button" onClick={toggleFloatingMaximize} title={isMaximized ? 'Restore window size' : 'Maximize window'} aria-label={isMaximized ? 'Restore window size' : 'Maximize window'}>
                {isMaximized ? '❐' : '□'}
              </button>
              <button type="button" onClick={closeFloatingWindow} title="Close AI Copilot" aria-label="Close AI Copilot">×</button>
            </div>
          </div>
          <div className="floating-window-content">{renderCopilotContent(false)}</div>
          {!isMaximized && ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'].map((direction) => (
            <div
              key={direction}
              className={`floating-window-resize-handle resize-${direction}`}
              onPointerDown={(event) => handleFloatingResizeStart(event, direction)}
              onPointerMove={handleFloatingResizeMove}
              onPointerUp={handleFloatingResizeEnd}
              onPointerCancel={handleFloatingResizeEnd}
              aria-hidden="true"
            />
          ))}
        </section>
      )}
    </div>
  );
}
