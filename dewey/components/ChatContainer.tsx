import React, { useEffect, useRef } from 'react';
import { marked } from 'marked';

interface ChatContainerProps {
  currentChat: {
    messages: Array<{ content: string; isUser: boolean }>;
    thinkingSections: Array<{ thoughts: Array<{ type: string; content: string; details?: string }> }>;
  } | null;
  socket: any;
}

const ChatContainer: React.FC<ChatContainerProps> = ({ currentChat, socket }) => {
  const chatContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [currentChat]);

  if (!currentChat) return null;

  return (
    <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-4 bg-gray-900">
      {currentChat.messages.map((message, index) => (
        <div
          key={index}
          className={`mb-4 ${
            message.isUser ? 'text-right text-cyan-300' : 'text-left text-white'
          }`}
        >
          <div
            className={`inline-block p-2 rounded-lg ${
              message.isUser ? 'bg-cyan-800' : 'bg-gray-700'
            }`}
          >
            {message.isUser ? (
              message.content
            ) : (
              <div dangerouslySetInnerHTML={{ __html: marked(message.content) }} />
            )}
          </div>
        </div>
      ))}
      {currentChat.thinkingSections.map((section, sectionIndex) => (
        <div key={sectionIndex} className="mb-4 border-l-2 border-gray-600 pl-4">
          {section.thoughts.map((thought, thoughtIndex) => (
            <div key={thoughtIndex} className="mb-2">
              <div className={`font-bold ${getThoughtColor(thought.type)}`}>
                {thought.type}:
              </div>
              <div dangerouslySetInnerHTML={{ __html: marked(thought.content) }} />
              {thought.details && (
                <pre className="mt-2 p-2 bg-gray-800 rounded">
                  {thought.details}
                </pre>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

function getThoughtColor(type: string): string {
  switch (type.toLowerCase()) {
    case 'plan':
      return 'text-blue-400';
    case 'decision':
      return 'text-green-400';
    case 'tool_call':
      return 'text-yellow-400';
    case 'tool_result':
      return 'text-purple-400';
    case 'think_more':
      return 'text-pink-400';
    case 'answer':
      return 'text-red-400';
    default:
      return 'text-gray-400';
  }
}

export default ChatContainer;