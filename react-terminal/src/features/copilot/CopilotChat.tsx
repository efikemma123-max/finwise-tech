import { useState } from 'react';
import './CopilotChat.css';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export function CopilotChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hi! I\'m Finwise Copilot. How can I help you with your trading today? I can analyze market trends, help with trade decisions, or answer questions about your portfolio.',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    // Simulate AI response
    setTimeout(() => {
      const assistantMessage: Message = {
        id: `msg-${Date.now()}-response`,
        role: 'assistant',
        content: 'Based on current market analysis, BTC is showing strong support at $48,500. Consider scaling into positions on dips. ETH dominance is decreasing - bullish for altcoins. Would you like me to analyze specific trading opportunities?',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setLoading(false);
    }, 1000);
  };

  return (
    <div className="copilot-chat">
      {/* Chat Header */}
      <div className="chat-header">
        <h2>🤖 Finwise Copilot</h2>
        <span className="status online">Online</span>
      </div>

      {/* Messages Container */}
      <div className="messages-container">
        {messages.map((message) => (
          <div key={message.id} className={`message message-${message.role}`}>
            <div className="message-content">
              {message.content}
            </div>
            <div className="message-time">
              {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
        ))}
        {loading && (
          <div className="message message-assistant">
            <div className="message-content">
              <span className="typing-indicator">
                <span></span><span></span><span></span>
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="quick-prompts">
        <button className="quick-prompt-btn">📊 Analyze BTC</button>
        <button className="quick-prompt-btn">📈 Market Trends</button>
        <button className="quick-prompt-btn">🎯 Trading Tips</button>
      </div>

      {/* Input Area */}
      <form onSubmit={handleSendMessage} className="chat-input-form">
        <input
          type="text"
          placeholder="Ask Copilot anything..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="chat-input"
          disabled={loading}
        />
        <button type="submit" className="send-btn" disabled={loading || !input.trim()}>
          ➤
        </button>
      </form>
    </div>
  );
}
