import { useState, useEffect } from 'react'
import ChatTabs from './ChatTabs'
import ChatContainer from './ChatContainer'
import UserInput from './UserInput'

export default function ChatArea({ currentChatId, setCurrentChatId, chats, setChats, createNewChat, socket }) {
  const [userInput, setUserInput] = useState('')

  const sendMessage = () => {
    if (userInput.trim() && currentChatId) {
      const newMessage = { content: userInput, isUser: true }
      setChats(prevChats => ({
        ...prevChats,
        [currentChatId]: {
          ...prevChats[currentChatId],
          messages: [...prevChats[currentChatId].messages, newMessage],
          thinkingSections: [...prevChats[currentChatId].thinkingSections, { thoughts: [] }]
        }
      }))
      socket.emit('chat_request', { 
        message: userInput,
        conversation_history: chats[currentChatId].messages
          .filter(m => !m.isUser).map(m => ({ role: 'assistant', content: m.content }))
          .concat(chats[currentChatId].messages.filter(m => m.isUser).map(m => ({ role: 'user', content: m.content })))
      })
      setUserInput('')
    }
  }

  const switchToChat = (chatId: string) => {
    setCurrentChatId(chatId);
  }

  const closeChat = (chatId: string) => {
    if (window.confirm('Are you sure you want to close this chat?')) {
      setChats(prevChats => {
        const newChats = { ...prevChats };
        delete newChats[chatId];
        return newChats;
      });
      if (currentChatId === chatId) {
        const remainingChatIds = Object.keys(chats).filter(id => id !== chatId);
        if (remainingChatIds.length > 0) {
          switchToChat(remainingChatIds[0]);
        } else {
          createNewChat();
        }
      }
    }
  }

  useEffect(() => {
    if (socket) {
      socket.on('thinking', (data) => {
        // Handle thinking event
        setChats(prevChats => ({
          ...prevChats,
          [currentChatId]: {
            ...prevChats[currentChatId],
            thinkingSections: [
              ...prevChats[currentChatId].thinkingSections,
              { thoughts: [{ type: 'thinking', content: data.step }] }
            ]
          }
        }));
      });

      socket.on('thought', (data) => {
        // Handle thought event
        setChats(prevChats => ({
          ...prevChats,
          [currentChatId]: {
            ...prevChats[currentChatId],
            thinkingSections: prevChats[currentChatId].thinkingSections.map((section, index) => 
              index === prevChats[currentChatId].thinkingSections.length - 1
                ? { ...section, thoughts: [...section.thoughts, data] }
                : section
            )
          }
        }));
      });

      socket.on('chat_response', (data) => {
        // Handle chat response event
        setChats(prevChats => ({
          ...prevChats,
          [currentChatId]: {
            ...prevChats[currentChatId],
            messages: [...prevChats[currentChatId].messages, { content: data.response, isUser: false }]
          }
        }));
      });

      socket.on('error', (data) => {
        // Handle error event
        console.error('Error:', data.message);
        // You might want to display this error to the user
      });
    }

    return () => {
      if (socket) {
        socket.off('thinking');
        socket.off('thought');
        socket.off('chat_response');
        socket.off('error');
      }
    };
  }, [socket, currentChatId, setChats]);

  return (
    <div className="flex flex-col flex-1">
      <ChatTabs
        chats={chats}
        currentChatId={currentChatId}
        createNewChat={createNewChat}
        switchToChat={switchToChat}
        closeChat={closeChat}
      />
      {currentChatId && (
        <ChatContainer
          currentChat={chats[currentChatId]}
          socket={socket}
        />
      )}
      <UserInput
        value={userInput}
        onChange={setUserInput}
        onSend={sendMessage}
      />
    </div>
  )
}