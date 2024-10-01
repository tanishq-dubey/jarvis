'use client'

import { useState, useEffect } from 'react'
import ChatArea from '../components/ChatArea'
import Sidebar from '../components/Sidebar'
import useSocket from '../hooks/useSocket'
import useLocalStorage from '../hooks/useLocalStorage'

export default function Home() {
  const [currentChatId, setCurrentChatId] = useState<string | null>(null)
  const [chats, setChats] = useLocalStorage('chats', {})
  const socket = useSocket()

  useEffect(() => {
    if (Object.keys(chats).length === 0) {
      createNewChat()
    } else {
      setCurrentChatId(Object.keys(chats)[0])
    }
  }, [])

  const createNewChat = () => {
    const chatId = Date.now().toString()
    setChats(prevChats => ({
      ...prevChats,
      [chatId]: { messages: [], thinkingSections: [] }
    }))
    setCurrentChatId(chatId)
  }

  return (
    <div className="flex h-screen">
      <ChatArea
        currentChatId={currentChatId}
        setCurrentChatId={setCurrentChatId}
        chats={chats}
        setChats={setChats}
        createNewChat={createNewChat}
        socket={socket}
      />
      <Sidebar socket={socket} />
    </div>
  )
}
