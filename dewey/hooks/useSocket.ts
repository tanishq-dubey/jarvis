import { useEffect, useState } from 'react'
import io from 'socket.io-client'

export default function useSocket() {
  const [socket, setSocket] = useState<any>(null)

  useEffect(() => {
    const newSocket = io('http://localhost:5001')
    setSocket(newSocket)
    return () => newSocket.close()
  }, [])

  return socket
}