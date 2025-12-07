import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [username, setUsername] = useState('');
  const [groupId, setGroupId] = useState('');
  const [messages, setMessages] = useState([]);
  const [users, setUsers] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  const [error, setError] = useState('');
  
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const connectWebSocket = useCallback((user, group) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }

    setError('');
    const wsUrl = `${WS_URL}/ws/${encodeURIComponent(user)}/${encodeURIComponent(group)}`;
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
        handleWebSocketMessage(data);
      } catch (e) {
        console.error('Error parsing WebSocket message:', e);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setError('Connection error. Please check your connection.');
    };

    ws.onclose = (event) => {
      console.log('WebSocket disconnected', event.code, event.reason);
      setIsConnected(false);
      
      // Reconnect if not a normal closure and still supposed to be connected
      if (event.code !== 1000 && username && groupId) {
        if (!reconnectTimeoutRef.current) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting to reconnect...');
            connectWebSocket(username, groupId);
          }, 3000);
        }
      }
    };

    wsRef.current = ws;
  }, []);

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
        setMessages(prev => [...prev, {
          id: data.message_id || 'msg-' + Date.now(),
          type: 'user',
          username: data.username,
          content: data.content,
          timestamp: new Date(data.timestamp)
        }]);
        break;
      
      case 'messages':
        // Batch messages
        if (data.messages && Array.isArray(data.messages)) {
          setMessages(prev => [...prev, ...data.messages.map(msg => ({
            id: msg.message_id || 'msg-' + Date.now(),
            type: 'user',
            username: msg.username,
            content: msg.content,
            timestamp: new Date(msg.timestamp)
          }))]);
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
      
      default:
        console.log('Unknown message type:', data.type);
    }
  }, []);

  const handleJoin = (e) => {
    e.preventDefault();
    const trimmedUsername = username.trim();
    const trimmedGroupId = groupId.trim().toUpperCase();

    if (!trimmedUsername) {
      setError('Please enter a username');
      return;
    }

    if (!trimmedGroupId || trimmedGroupId.length > 4 || !/^[A-Za-z0-9]+$/.test(trimmedGroupId)) {
      setError('Group ID must be 1-4 alphanumeric characters');
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

    try {
      wsRef.current.send(JSON.stringify({ message: trimmed }));
      setMessageInput('');
    } catch (error) {
      console.error('Error sending message:', error);
      setError('Failed to send message');
    }
  };

  const handleDisconnect = () => {
    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
    }
    setIsConnected(false);
    setMessages([]);
    setUsers([]);
    setUsername('');
    setGroupId('');
    setError('');
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

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
                <label htmlFor="groupid">Group ID (1-4 alphanumeric)</label>
                <input
                  id="groupid"
                  type="text"
                  value={groupId}
                  onChange={(e) => setGroupId(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                  placeholder="e.g., ABC1"
                  maxLength={4}
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
            <h2>Group: {groupId}</h2>
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
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSendMessage} className="message-form">
            <input
              type="text"
              value={messageInput}
              onChange={(e) => setMessageInput(e.target.value)}
              placeholder="Type a message..."
              maxLength={1000}
              disabled={!isConnected}
              autoFocus
            />
            <button type="submit" disabled={!isConnected || !messageInput.trim()}>
              Send
            </button>
          </form>

          {error && <div className="error-message">{error}</div>}
        </div>
      </div>
    </div>
  );
}

export default App;

