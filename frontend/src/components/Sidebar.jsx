import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  searchQuery,
  onSearchChange,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onRenameConversation,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');

  const startRename = (conv, e) => {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditValue(conv.title || '');
  };

  const commitRename = (id) => {
    const title = editValue.trim();
    if (title) onRenameConversation(id, title);
    setEditingId(null);
  };

  const handleDelete = (id, e) => {
    e.stopPropagation();
    if (window.confirm('Delete this conversation? This cannot be undone.')) {
      onDeleteConversation(id);
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <input
        className="conversation-search"
        type="text"
        placeholder="Search title &amp; messages…"
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
      />

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">
            {searchQuery.trim() ? 'No matches' : 'No conversations yet'}
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() =>
                editingId !== conv.id && onSelectConversation(conv.id)
              }
            >
              {editingId === conv.id ? (
                <input
                  className="conversation-rename-input"
                  autoFocus
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(conv.id);
                    if (e.key === 'Escape') setEditingId(null);
                  }}
                  onBlur={() => commitRename(conv.id)}
                />
              ) : (
                <>
                  <div className="conversation-title">
                    <span className="conversation-title-text">
                      {conv.title || 'New Conversation'}
                    </span>
                    <span className="conv-actions">
                      <button
                        className="conv-action-btn"
                        title="Rename"
                        onClick={(e) => startRename(conv, e)}
                      >
                        ✎
                      </button>
                      <button
                        className="conv-action-btn"
                        title="Delete"
                        onClick={(e) => handleDelete(conv.id, e)}
                      >
                        ×
                      </button>
                    </span>
                  </div>
                  <div className="conversation-meta">
                    {conv.message_count} messages
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
