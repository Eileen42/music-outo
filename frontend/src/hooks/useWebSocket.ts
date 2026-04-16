import { useEffect, useRef, useState } from 'react'

const BASE_WS = (localStorage.getItem('backend_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000')
  .replace(/^https/, 'wss')
  .replace(/^http/, 'ws')

interface WSMessage {
  type: 'progress' | 'log' | 'done' | 'error'
  project_id: string
  data: unknown
}

export function useWebSocket(projectId: string | null) {
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!projectId) return

    const ws = new WebSocket(`${BASE_WS}/ws/${projectId}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const msg: WSMessage = JSON.parse(e.data)
        setLastMessage(msg)
      } catch {
        // ignore
      }
    }

    ws.onerror = () => {
      // silent — WS is optional, polling fallback handles updates
    }

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 30_000)

    return () => {
      clearInterval(ping)
      ws.close()
    }
  }, [projectId])

  return lastMessage
}
