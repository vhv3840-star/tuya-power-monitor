import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type {MonitorState} from './types'

export function useMonitor(enabled: boolean) {
  const [state, setState] = useState<MonitorState | null>(null)
  const [connection, setConnection] = useState<'connecting'|'live'|'retrying'>('connecting')
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    if (!enabled) return
    try {setState(await api<MonitorState>('/api/state')); setError('')} catch(e) {setError((e as Error).message)}
  }, [enabled])
  useEffect(() => {
    if (!enabled) {setState(null); return}
    let socket: WebSocket | undefined, retry: ReturnType<typeof setTimeout>, stopped = false
    let attempt = 0
    const connect = () => {
      if (stopped) return
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      socket.onopen = () => {attempt = 0; setConnection('live'); setError('')}
      socket.onmessage = event => {try {setState(JSON.parse(event.data)); setError('')} catch {setError('Не удалось прочитать обновление')}}
      socket.onclose = () => {if (!stopped) {setConnection('retrying'); retry = setTimeout(connect, Math.min(10000, 1000 * 2 ** attempt++))}}
      socket.onerror = () => socket?.close()
    }
    refresh(); connect()
    const timer = setInterval(refresh, 10000)
    return () => {stopped = true; socket?.close(); clearTimeout(retry); clearInterval(timer)}
  }, [enabled, refresh])
  return {state, connection, error, refresh}
}

export function useQuery<T>(path: string | null, revision = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {setData(null); setError('')}, [path])
  useEffect(() => {
    let alive = true
    if (!path) return
    api<T>(path).then(value => {if(alive) {setData(value); setError('')}}).catch(e => {if(alive) setError(e.message)})
    return () => {alive = false}
  }, [path, revision])
  return {data, error}
}
