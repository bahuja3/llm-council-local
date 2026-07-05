import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './ChatInterface.css';

const councilMetaRow = { display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center', margin: '2px 0 12px' };
const councilBadge = { fontSize: '11px', padding: '2px 8px', borderRadius: '10px', background: '#eef2f7', color: '#3a4a5a', border: '1px solid #dbe3ec', whiteSpace: 'nowrap' };
const councilSeat = { fontSize: '11px', padding: '2px 8px', borderRadius: '10px', background: '#f5f5f5', color: '#666', fontFamily: 'ui-monospace, monospace', whiteSpace: 'nowrap' };

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const [webMode, setWebMode] = useState('auto'); // 'auto' | 'on' | 'off'
  const [fast, setFast] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      const forceSearch = webMode === 'auto' ? null : webMode === 'on';
      onSendMessage(input, { fast, forceSearch });
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  {msg.metadata && (msg.metadata.council || msg.metadata.fast != null) && (
                    <div style={councilMetaRow}>
                      <span style={councilBadge}>
                        {msg.metadata.fast ? '⚡ Fast' : '🧠 Full'}
                      </span>
                      {msg.metadata.search?.searched && (
                        <span style={councilBadge}>
                          🌐 web
                          {msg.metadata.search.results
                            ? ` · ${msg.metadata.search.results}`
                            : ''}
                        </span>
                      )}
                      {(msg.metadata.signals || [])
                        .filter((s) => s !== 'websearch')
                        .map((s) => (
                          <span key={s} style={councilBadge}>
                            🎯 {s}
                          </span>
                        ))}
                      {(msg.metadata.council || []).map((m) => (
                        <span key={m} style={councilSeat}>
                          {m}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

        <form className="input-form" onSubmit={handleSubmit}>
          <div className="council-options" style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '8px', fontSize: '13px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: '#666' }}>🌐 Web</span>
              {['auto', 'on', 'off'].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setWebMode(m)}
                  disabled={isLoading}
                  style={{
                    padding: '2px 10px',
                    borderRadius: '12px',
                    border: '1px solid ' + (webMode === m ? '#4a90e2' : '#ccc'),
                    background: webMode === m ? '#4a90e2' : '#fff',
                    color: webMode === m ? '#fff' : '#555',
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                  }}
                >
                  {m}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setFast((f) => !f)}
              disabled={isLoading}
              title="Fast mode: lighter all-resident council; 5th seat auto-picks reasoning (Meta) vs web (Cohere)"
              style={{
                padding: '2px 12px',
                borderRadius: '12px',
                border: '1px solid ' + (fast ? '#e2a04a' : '#ccc'),
                background: fast ? '#e2a04a' : '#fff',
                color: fast ? '#fff' : '#555',
                cursor: 'pointer',
              }}
            >
              ⚡ Fast {fast ? 'on' : 'off'}
            </button>
          </div>
          <textarea
            className="message-input"
            placeholder={
              conversation.messages.length === 0
                ? 'Ask your question… (Shift+Enter for newline, Enter to send)'
                : 'Ask a follow-up… (the council sees the conversation so far)'
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading}
          >
            Send
          </button>
        </form>
    </div>
  );
}
