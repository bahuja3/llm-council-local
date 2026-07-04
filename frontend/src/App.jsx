import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [streamingId, setStreamingId] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  // In-progress stream state, kept in refs so it survives navigating away & back.
  const streamRef = useRef(null); // { id, conversation }
  const currentIdRef = useRef(null); // latest currentConversationId (for async callbacks)

  // Load / search conversations (debounced) on mount and whenever the query changes
  useEffect(() => {
    const t = setTimeout(() => {
      loadConversations();
    }, 200);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // Load conversation details when selected. If the selected conversation is
  // mid-stream, restore its in-progress state from the ref instead of refetching
  // (which would drop the streaming progress and orphan the spinner).
  useEffect(() => {
    currentIdRef.current = currentConversationId;
    if (!currentConversationId) return;
    if (streamRef.current && streamRef.current.id === currentConversationId) {
      setCurrentConversation(streamRef.current.conversation);
    } else {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations(searchQuery);
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleDeleteConversation = async (id) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (streamRef.current && streamRef.current.id === id) {
        streamRef.current = null;
      }
      setStreamingId((cur) => (cur === id ? null : cur));
      if (id === currentConversationId) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const handleRenameConversation = async (id, title) => {
    try {
      await api.renameConversation(id, title);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title } : c))
      );
      setCurrentConversation((prev) =>
        prev && prev.id === id ? { ...prev, title } : prev
      );
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    }
  };

  const handleSendMessage = async (content, options = {}) => {
    const targetId = currentConversationId;
    if (!targetId) return;

    // Build the optimistic conversation (user message + progressive assistant
    // placeholder) and stash it in a ref so it survives navigating away & back.
    const userMessage = { role: 'user', content };
    const assistantMessage = {
      role: 'assistant',
      stage1: null,
      stage2: null,
      stage3: null,
      metadata: null,
      loading: { stage1: false, stage2: false, stage3: false },
    };
    const base =
      currentConversation && currentConversation.id === targetId
        ? currentConversation
        : { id: targetId, messages: [] };
    const initialConv = {
      ...base,
      id: targetId,
      messages: [...base.messages, userMessage, assistantMessage],
    };
    streamRef.current = { id: targetId, conversation: initialConv };
    setStreamingId(targetId);
    setCurrentConversation((prev) =>
      prev && prev.id === targetId ? initialConv : prev
    );

    // Immutably patch the last (assistant) message of the in-progress conversation.
    // Guarded by targetId so a stream never writes into a different conversation;
    // reflected in the view only while that conversation is the one on screen.
    const patchLast = (mutate) => {
      const ref = streamRef.current;
      if (!ref || ref.id !== targetId) return;
      const messages = ref.conversation.messages.map((m, i, arr) =>
        i === arr.length - 1 ? { ...m, loading: { ...m.loading } } : m
      );
      mutate(messages[messages.length - 1]);
      const updated = { ...ref.conversation, messages };
      streamRef.current = { id: targetId, conversation: updated };
      setCurrentConversation((prev) =>
        prev && prev.id === targetId ? updated : prev
      );
    };

    const finish = () => {
      if (streamRef.current && streamRef.current.id === targetId) {
        streamRef.current = null;
      }
      setStreamingId((cur) => (cur === targetId ? null : cur));
    };

    try {
      await api.sendMessageStream(
        targetId,
        content,
        (eventType, event) => {
          switch (eventType) {
            case 'stage1_start':
              patchLast((m) => {
                m.loading.stage1 = true;
              });
              break;
            case 'stage1_complete':
              patchLast((m) => {
                m.stage1 = event.data;
                m.loading.stage1 = false;
              });
              break;
            case 'stage2_start':
              patchLast((m) => {
                m.loading.stage2 = true;
              });
              break;
            case 'stage2_complete':
              patchLast((m) => {
                m.stage2 = event.data;
                m.metadata = event.metadata;
                m.loading.stage2 = false;
              });
              break;
            case 'stage3_start':
              patchLast((m) => {
                m.loading.stage3 = true;
              });
              break;
            case 'stage3_complete':
              patchLast((m) => {
                m.stage3 = event.data;
                m.loading.stage3 = false;
              });
              break;
            case 'title_complete':
              loadConversations();
              break;
            case 'complete':
              finish();
              loadConversations();
              break;
            case 'error':
              console.error('Stream error:', event.message);
              finish();
              if (currentIdRef.current === targetId) loadConversation(targetId);
              break;
            default:
              console.log('Unknown event type:', eventType);
          }
        },
        options
      );
    } catch (error) {
      console.error('Failed to send message:', error);
      finish();
      // Reconcile the view with what actually got saved server-side.
      if (currentIdRef.current === targetId) loadConversation(targetId);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onDeleteConversation={handleDeleteConversation}
        onRenameConversation={handleRenameConversation}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={streamingId != null && streamingId === currentConversationId}
      />
    </div>
  );
}

export default App;
