import React from 'react';

interface ChatTabsProps {
  chats: Record<string, any>;
  currentChatId: string | null;
  createNewChat: () => void;
  switchToChat: (chatId: string) => void;
  closeChat: (chatId: string) => void;
}

const ChatTabs: React.FC<ChatTabsProps> = ({ chats, currentChatId, createNewChat, switchToChat, closeChat }) => {
  return (
    <div className="flex bg-gray-800 p-2">
      {Object.keys(chats).map((chatId) => (
        <div
          key={chatId}
          className={`px-4 py-2 mr-2 rounded-t-lg flex items-center ${
            chatId === currentChatId ? 'bg-gray-600' : 'bg-gray-700'
          }`}
        >
          <button
            onClick={() => switchToChat(chatId)}
            className="flex-grow text-left"
          >
            Chat {chatId}
          </button>
          <button 
            className="ml-2 text-red-500 hover:text-red-700"
            onClick={(e) => {
              e.stopPropagation();
              closeChat(chatId);
            }}
          >
            ×
          </button>
        </div>
      ))}
      <button
        className="px-4 py-2 bg-green-600 rounded-t-lg"
        onClick={createNewChat}
      >
        + New Chat
      </button>
    </div>
  );
};

export default ChatTabs;