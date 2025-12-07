import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

// Get WebSocket URL - use same host as current page
const getWebSocketURL = () => {
  const envUrl = process.env.REACT_APP_WS_URL;
  if (envUrl) {
    return envUrl;
  }
  // Use same protocol and host as current page (works with ngrok too)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host; // Use same host as the page (includes port if any)
  return `${protocol}//${host}`;
};

const WS_URL = getWebSocketURL();

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [username, setUsername] = useState('');
  const [groupId, setGroupId] = useState('');
  const [messages, setMessages] = useState([]);
  const [users, setUsers] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  const [error, setError] = useState('');
  const [rateLimitSeconds, setRateLimitSeconds] = useState(0);
  const [isRateLimited, setIsRateLimited] = useState(false);
  const [pendingMessage, setPendingMessage] = useState('');
  const [typingUsers, setTypingUsers] = useState([]);
  
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const rateLimitIntervalRef = useRef(null);
  const pendingMessageRef = useRef('');
  const usernameRef = useRef(username);
  const startRateLimitCountdownRef = useRef(null);
  const typingTimeoutRef = useRef(null);
  const lastTypingSentRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Update refs when state changes
  useEffect(() => {
    usernameRef.current = username;
  }, [username]);

  // Use ref for message handler to avoid circular dependencies
  const handleWebSocketMessageRef = useRef(null);

  const handleWebSocketMessage = useCallback((data) => {
    switch (data.type) {
      case 'welcome':
        setUsers(data.users || []);
        setMessages(prev => [{
          id: 'system-' + Date.now(),
          type: 'system',
          content: data.message,
          timestamp: new Date()
        }, ...prev]);
        break;
      
      case 'message':
        const messageId = data.message_id || 'msg-' + Date.now();
        setMessages(prev => {
          // Check if message already exists to prevent duplicates
          if (prev.some(msg => msg.id === messageId)) {
            return prev;
          }
          // If this is our own message, clear pending message
          if (data.username === usernameRef.current && pendingMessageRef.current) {
            setPendingMessage('');
            pendingMessageRef.current = '';
          }
          return [...prev, {
            id: messageId,
            type: 'user',
            username: data.username,
            content: data.content,
            timestamp: new Date(data.timestamp)
          }];
        });
        break;
      
      case 'messages':
        // Batch messages
        if (data.messages && Array.isArray(data.messages)) {
          setMessages(prev => {
            const existingIds = new Set(prev.map(msg => msg.id));
            const newMessages = data.messages
              .map(msg => ({
                id: msg.message_id || 'msg-' + Date.now(),
                type: 'user',
                username: msg.username,
                content: msg.content,
                timestamp: new Date(msg.timestamp)
              }))
              .filter(msg => !existingIds.has(msg.id));
            return [...prev, ...newMessages];
          });
        }
        break;
      
      case 'user_joined':
        setUsers(prev => {
          if (!prev.includes(data.username)) {
            return [...prev, data.username];
          }
          return prev;
        });
        setMessages(prev => [{
          id: 'system-' + Date.now(),
          type: 'system',
          content: `${data.username} joined the group`,
          timestamp: new Date(data.timestamp)
        }, ...prev]);
        break;
      
      case 'user_left':
        setUsers(prev => prev.filter(u => u !== data.username));
        setMessages(prev => [{
          id: 'system-' + Date.now(),
          type: 'system',
          content: `${data.username} left the group`,
          timestamp: new Date(data.timestamp)
        }, ...prev]);
        break;
      
      case 'rate_limit':
        const remaining = data.remaining_seconds || 5;
        setRateLimitSeconds(remaining);
        setIsRateLimited(true);
        if (startRateLimitCountdownRef.current) {
          startRateLimitCountdownRef.current(remaining);
        }
        setError(`⏱️ Rate limited! Please wait ${remaining} seconds before sending another message`);
        // Restore the message that was blocked
        if (pendingMessageRef.current) {
          setMessageInput(pendingMessageRef.current);
          setPendingMessage('');
          pendingMessageRef.current = '';
        }
        break;
      
      case 'typing':
        if (data.typing_users && Array.isArray(data.typing_users)) {
          // Filter out current user from typing list
          const othersTyping = data.typing_users.filter(u => u !== usernameRef.current);
          setTypingUsers(othersTyping);
        }
        break;
      
      default:
        console.log('Unknown message type:', data.type);
    }
  }, []);

  // Update the ref whenever the handler changes
  useEffect(() => {
    handleWebSocketMessageRef.current = handleWebSocketMessage;
  }, [handleWebSocketMessage]);

  const connectWebSocket = useCallback((user, group) => {
    // Close existing connection if open
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.log('Closing existing WebSocket before creating new one');
      wsRef.current.close(1000, 'Reconnecting');
    }
    
    // Clear any pending reconnection attempts
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setError('');
    const wsUrl = `${WS_URL}/ws/${encodeURIComponent(user)}/${encodeURIComponent(group)}`;
    console.log('Creating new WebSocket connection:', wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      setError('');
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (handleWebSocketMessageRef.current) {
          handleWebSocketMessageRef.current(data);
        }
      } catch (e) {
        console.error('Error parsing WebSocket message:', e);
      }
    };

    ws.onerror = (error) => {
      // Log the error for debugging, but don't show it if it's just an extension error
      console.error('WebSocket error:', error);
      // Only show error if connection is not already closed
      // Extension errors won't affect the actual WebSocket connection
      if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
        // This might be a real connection error
        console.warn('Potential WebSocket connection issue detected');
      }
      // Don't set error state here - let onclose handle it based on close code
    };

    ws.onclose = (event) => {
      console.log('WebSocket disconnected', event.code, event.reason);
      setIsConnected(false);
      
      // Handle different close codes
      if (event.code === 1000) {
        // Normal closure - user disconnected
        setError('');
      } else if (event.code === 1006) {
        // Abnormal closure - connection lost
        setError('Connection lost. Attempting to reconnect...');
      } else if (event.code === 1008) {
        // Policy violation - show the reason
        setError(event.reason || 'Connection rejected. Please check your room name and username.');
      } else if (event.code === 1011) {
        // Server error
        setError('Server error occurred. Attempting to reconnect...');
      } else if (event.code !== 1000) {
        // Other errors
        setError('Connection closed. Attempting to reconnect...');
      }
      
      // Reconnect if not a normal closure and still supposed to be connected
      if (event.code !== 1000 && usernameRef.current && groupId) {
        if (!reconnectTimeoutRef.current) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting to reconnect...');
            setError('Reconnecting...');
            connectWebSocket(usernameRef.current, groupId);
          }, 3000);
        }
      }
    };

    wsRef.current = ws;
  }, [groupId]);

  const startRateLimitCountdown = useCallback((seconds) => {
    // Clear any existing interval
    if (rateLimitIntervalRef.current) {
      clearInterval(rateLimitIntervalRef.current);
    }
    
    setRateLimitSeconds(seconds);
    setIsRateLimited(true);
    
    rateLimitIntervalRef.current = setInterval(() => {
      setRateLimitSeconds(prev => {
        if (prev <= 1) {
          setIsRateLimited(false);
          if (rateLimitIntervalRef.current) {
            clearInterval(rateLimitIntervalRef.current);
            rateLimitIntervalRef.current = null;
          }
          setError('');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  // Update the ref whenever the countdown function changes
  useEffect(() => {
    startRateLimitCountdownRef.current = startRateLimitCountdown;
  }, [startRateLimitCountdown]);

  const handleJoin = (e) => {
    e.preventDefault();
    const trimmedUsername = username.trim();
    const trimmedGroupId = groupId.trim().toUpperCase().replace(/[^A-Z0-9]/g, '');

    if (!trimmedUsername) {
      setError('Please enter a username');
      return;
    }

    if (trimmedGroupId.length !== 5) {
      setError('Room name must be exactly 5 alphanumeric characters');
      return;
    }

    setGroupId(trimmedGroupId);
    connectWebSocket(trimmedUsername, trimmedGroupId);
  };

  const handleSendMessage = (e) => {
    e.preventDefault();
    const trimmed = messageInput.trim();

    if (!trimmed || !isConnected || wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    if (isRateLimited) {
      setError(`⏱️ Please wait ${rateLimitSeconds} seconds before sending another message`);
      return;
    }

    try {
      // Stop typing indicator
      sendTypingIndicator(false);
      
      // Store the message before sending (in case we need to restore it)
      const messageToSend = trimmed;
      setPendingMessage(messageToSend);
      pendingMessageRef.current = messageToSend;
      
      wsRef.current.send(JSON.stringify({ message: messageToSend }));
      
      // Clear input optimistically (will be restored if rate limited)
      setMessageInput('');
      setError(''); // Clear any previous errors
      
      // Start optimistic rate limit countdown (backend will correct if needed)
      if (startRateLimitCountdownRef.current) {
        startRateLimitCountdownRef.current(5);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      setError('Failed to send message');
      // Restore message on error
      if (pendingMessageRef.current) {
        setMessageInput(pendingMessageRef.current);
        setPendingMessage('');
        pendingMessageRef.current = '';
      }
    }
  };

  const handleDisconnect = () => {
    // Stop typing indicator before disconnecting
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({ typing: false }));
      } catch (e) {
        // Ignore errors
      }
    }
    
    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
    }
    setIsConnected(false);
    setMessages([]);
    setUsers([]);
    setTypingUsers([]);
    setUsername('');
    setGroupId('');
    setError('');
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
  };

  // Send typing indicator when user types
  const sendTypingIndicator = useCallback((isTyping) => {
    if (!isConnected || wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    const now = Date.now();
    // Debounce: only send typing indicator max once per second
    if (isTyping && now - lastTypingSentRef.current < 1000) {
      return;
    }
    lastTypingSentRef.current = now;

    try {
      wsRef.current.send(JSON.stringify({ typing: isTyping }));
      
      // Clear existing timeout
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
      }
      
      // Auto-stop typing indicator after 2 seconds of no typing
      if (isTyping) {
        typingTimeoutRef.current = setTimeout(() => {
          sendTypingIndicator(false);
        }, 2000);
      }
    } catch (error) {
      console.error('Error sending typing indicator:', error);
    }
  }, [isConnected]);

  // Handle input change for typing indicator
  const handleInputChange = useCallback((e) => {
    const value = e.target.value;
    setMessageInput(value);
    
    // Send typing indicator if there's text
    if (value.trim() && !isRateLimited) {
      sendTypingIndicator(true);
    } else {
      sendTypingIndicator(false);
    }
  }, [sendTypingIndicator, isRateLimited]);

  // Cleanup on component unmount only (empty dependency array)
  useEffect(() => {
    return () => {
      // Only close if we're actually unmounting (not just re-rendering)
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        console.log('Component unmounting, closing WebSocket');
        wsRef.current.close(1000, 'Component unmounting');
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (rateLimitIntervalRef.current) {
        clearInterval(rateLimitIntervalRef.current);
      }
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
      }
      // Send stop typing on unmount
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({ typing: false }));
        } catch (e) {
          // Ignore errors on cleanup
        }
      }
    };
  }, []); // Empty dependency array - only run cleanup on unmount

  if (!isConnected) {
    return (
      <div className="app">
        <div className="join-container">
          <div className="join-card">
            <h1>PyChat</h1>
            <p className="subtitle">Real-time Group Chat</p>
            
            <form onSubmit={handleJoin} className="join-form">
              <div className="form-group">
                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter your username"
                  maxLength={50}
                  autoComplete="off"
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label htmlFor="groupid">Room Name (exactly 5 characters)</label>
                <input
                  id="groupid"
                  type="text"
                  value={groupId}
                  onChange={(e) => setGroupId(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5))}
                  placeholder="e.g., ABC12"
                  maxLength={5}
                  autoComplete="off"
                />
              </div>

              {error && <div className="error-message">{error}</div>}

              <button type="submit" className="join-button">
                Join Chat
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="chat-container">
        <div className="chat-header">
          <div className="header-info">
            <h2>Room: {groupId}</h2>
            <span className={`status ${isConnected ? 'connected' : 'disconnected'}`}>
              {isConnected ? '● Connected' : '○ Disconnected'}
            </span>
          </div>
          <div className="header-users">
            <span className="users-count">{users.length} user{users.length !== 1 ? 's' : ''}</span>
            <button onClick={handleDisconnect} className="disconnect-button">
              Leave
            </button>
          </div>
        </div>

        <div className="users-sidebar">
          <h3>Users in Group</h3>
          <ul className="users-list">
            {users.map((user, index) => (
              <li key={index} className={user === username ? 'current-user' : ''}>
                {user === username ? '👤 ' : ''}{user}
                {user === username && <span className="you-badge">(You)</span>}
              </li>
            ))}
          </ul>
        </div>

        <div className="chat-main">
          <div className="messages-container">
            {messages.length === 0 ? (
              <div className="empty-state">
                <p>No messages yet. Start the conversation!</p>
              </div>
            ) : (
              messages.map((message) => (
                <div
                  key={message.id}
                  className={`message ${message.type === 'system' ? 'system-message' : ''} ${
                    message.username === username ? 'own-message' : ''
                  }`}
                >
                  {message.type === 'user' && (
                    <span className="message-username">{message.username}:</span>
                  )}
                  <span className="message-content">{message.content}</span>
                  <span className="message-time">
                    {new Date(message.timestamp).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </span>
                </div>
              ))
            )}
            {typingUsers.length > 0 && (
              <div className="typing-indicator">
                <span className="typing-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
                <span className="typing-text">
                  {typingUsers.length === 1 
                    ? `${typingUsers[0]} is typing...`
                    : typingUsers.length === 2
                    ? `${typingUsers[0]} and ${typingUsers[1]} are typing...`
                    : `${typingUsers[0]} and ${typingUsers.length - 1} others are typing...`
                  }
                </span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSendMessage} className="message-form">
            <div className={`input-wrapper ${isRateLimited ? 'rate-limited-input' : ''}`}>
            <input
              type="text"
              value={messageInput}
              onChange={handleInputChange}
              placeholder={isRateLimited ? "Input locked - please wait..." : "Type a message..."}
              maxLength={1000}
              disabled={!isConnected}
              autoFocus
            />
            </div>
            <button 
              type="submit" 
              disabled={!isConnected || !messageInput.trim() || isRateLimited}
              className={isRateLimited ? 'rate-limited' : ''}
            >
              {isRateLimited ? (
                <span className="send-button-content">
                  <div className="send-button-loader">
                    <svg className="send-button-spinner" viewBox="0 0 24 24">
                      <circle
                        className="send-button-circle-bg"
                        cx="12"
                        cy="12"
                        r="10"
                        fill="none"
                        stroke="rgba(255, 255, 255, 0.3)"
                        strokeWidth="2"
                      />
                      <circle
                        className="send-button-circle"
                        cx="12"
                        cy="12"
                        r="10"
                        fill="none"
                        stroke="white"
                        strokeWidth="2"
                        strokeLinecap="round"
                      strokeDasharray={`${2 * Math.PI * 10}`}
                      strokeDashoffset={`${2 * Math.PI * 10 * (1 - rateLimitSeconds / 5)}`}
                      style={{
                        transform: 'rotate(-90deg)',
                        transformOrigin: '12px 12px'
                      }}
                      />
                    </svg>
                  </div>
                  <span className="send-button-counter">{rateLimitSeconds}s</span>
                </span>
              ) : (
                'Send'
              )}
            </button>
          </form>

          {error && <div className="error-message">{error}</div>}
        </div>
      </div>
    </div>
  );
}

export default App;

