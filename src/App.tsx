import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Activity, ArrowLeft, ArrowRight, BarChart3, Bell, Cable, Check, ChevronDown, CircleHelp, Clock3, FlaskConical, LayoutDashboard, LoaderCircle, LogOut, Menu, MoreHorizontal, PlugZap, Settings2, ShieldCheck, Wifi, X, Zap } from 'lucide-react'
import { api, send } from './api'
import { useMonitor, useQuery } from './hooks'
import { Badge, Brand, Busy, date, Empty, Note } from './components'
import Dashboard from './pages/Dashboard'
import Monitoring from './pages/Monitoring'
import History from './pages/History'
import Analytics from './pages/Analytics'
import Automation from './pages/Automation'
import Devices from './pages/Devices'
import Settings from './pages/Settings'
import ConnectionSetup from './pages/ConnectionSetup'
import type { Page, Run, Stats } from './types'

const navigation = [
  {id:'dashboard',label:'Главная панель',icon:LayoutDashboard}, {id:'live',label:'Мониторинг',icon:Activity},
  {id:'history',label:'История зарядок',icon:Clock3}, {id:'analytics',label:'Аналитика энергии',icon:BarChart3},
  {id:'automation',label:'Автоматизация',icon:Zap}, {id:'devices',label:'Устройства',icon:PlugZap},
  {id:'connection',label:'Подключение',icon:Cable},
  {id:'settings',label:'Настройки',icon:Settings2},
] as const
const phoneNavigation = [
  {id:'dashboard',label:'Дом',icon:LayoutDashboard},
  {id:'live',label:'В эфире',icon:Activity},
  {id:'history',label:'История',icon:Clock3},
  {id:'automation',label:'Правила',icon:Zap},
] as const
export default function App() {
  const initialPage=location.hash.slice(1)
  const [page,setPage]=useState<Page>(navigation.some(n=>n.id===initialPage)?initialPage as Page:'dashboard')
  const [auth,setAuth]=useState<boolean|null>(null)
  const [authError,setAuthError]=useState('')
  const [password,setPassword]=useState('')
  const [busy,setBusy]=useState(false)
  const [selected,setSelected]=useState(localStorage.getItem('tuya-device')||'')
  const [period,setPeriod]=useState('day')
  const [mobile,setMobile]=useState(false)
  const sidebarRef=useRef<HTMLElement>(null)
  const [notifications,setNotifications]=useState(false)
  const [help,setHelp]=useState(false)
  const [toast,setToast]=useState<{message:string;error:boolean}|null>(null)
  const [now,setNow]=useState(Date.now()/1000)
  const [revision,setRevision]=useState(0)
  const {state,connection,error,refresh}=useMonitor(auth===true)
  const device=state?.devices.find(d=>d.id===selected)||state?.devices[0]
  const [statsError,setStatsError]=useState('')
  const [stats,setStats]=useState<Stats|null>(null)
  const lastCompleted = useRef<number|null>(null)
  useEffect(()=>{document.documentElement.dataset.density=localStorage.getItem('tuya-density')||'comfortable';api<{authenticated:boolean}>('/auth/status').then(r=>setAuth(r.authenticated)).catch(e=>setAuthError(e.message))},[])
  useEffect(()=>{const expired=()=>{setMobile(false);setAuth(false)};window.addEventListener('auth-expired',expired);return()=>window.removeEventListener('auth-expired',expired)},[])
  useEffect(()=>{const id=setInterval(()=>setNow(Date.now()/1000),1000);return()=>clearInterval(id)},[])
  useEffect(()=>{const handler=()=>{const p=location.hash.slice(1);if(navigation.some(n=>n.id===p))setPage(p as Page)};window.addEventListener('hashchange',handler);return()=>window.removeEventListener('hashchange',handler)},[])
  useEffect(()=>{if(!toast)return;const id=setTimeout(()=>setToast(null),6000);return()=>clearTimeout(id)},[toast])
  useEffect(()=>{
    const media=window.matchMedia('(max-width: 760px)')
    const closeOnDesktop=()=>{if(!media.matches)setMobile(false)}
    media.addEventListener('change',closeOnDesktop)
    return()=>media.removeEventListener('change',closeOnDesktop)
  },[])
  useEffect(()=>{
    if(!mobile)return
    const previousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null
    const previousOverflow=document.body.style.overflow
    document.body.style.overflow='hidden'
    const frame=requestAnimationFrame(()=>sidebarRef.current?.querySelector<HTMLButtonElement>('.sidebar-close')?.focus())
    const keys=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();setMobile(false)}
      if(event.key!=='Tab')return
      const items=Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]')||[]).filter(el=>el.getClientRects().length>0)
      const first=items[0],last=items[items.length-1]
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
    }
    document.addEventListener('keydown',keys)
    return()=>{cancelAnimationFrame(frame);document.body.style.overflow=previousOverflow;document.removeEventListener('keydown',keys);if(previousFocus?.isConnected)previousFocus.focus({preventScroll:true})}
  },[mobile])
  useEffect(()=>{if(!state)return;const id=state.events.find(e=>e.kind==='completed')?.id||0;if(lastCompleted.current!==null&&id>lastCompleted.current&&state.preferences.notifications)setToast({message:'Сеанс зарядки завершён. Подробности в истории.',error:false});lastCompleted.current=id},[state?.events,state?.preferences.notifications])
  useEffect(()=>{setStats(null)},[device?.id,state?.preferences.mode,period])
  useEffect(()=>{
    if(!device||!auth)return
    let alive=true
    const load=()=>api<Stats>(`/api/analytics?device_id=${encodeURIComponent(device.id)}&period=${period}`).then(s=>{if(alive){setStats(s);setStatsError('')}}).catch(e=>{if(alive)setStatsError(e.message)})
    load();const timer=setInterval(load,10000)
    return()=>{alive=false;clearInterval(timer)}
  },[auth,device?.id,state?.preferences.mode,state?.preferences.tariff,period,revision])
  const navigate=(p:Page)=>{setPage(p);location.hash=p;setMobile(false);window.scrollTo({top:0,behavior:'smooth'})}
  const select=(id:string)=>{setSelected(id);localStorage.setItem('tuya-device',id)}
  const run:Run=useCallback(async(action,success)=>{setBusy(true);try{await action();await refresh();setRevision(v=>v+1);if(success)setToast({message:success,error:false});return true}catch(e){setToast({message:(e as Error).message,error:true});return false}finally{setBusy(false)}},[refresh])
  const login=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);try{await send('/auth/login',{password});setPassword('');setAuth(true);setAuthError('')}catch(e){setAuthError((e as Error).message)}finally{setBusy(false)}}
  if(auth===null||auth===false)return <div className="login-shell"><div className="login-orb"/><div className="login-card card"><Brand/><div className="eyebrow">YOUR ENERGY. CONNECTED.</div><h1>Добро пожаловать<br/>домой<span>.</span></h1>{auth===null&&!authError?<Busy/>:<form onSubmit={login}><p className="muted">Введите APP_PASSWORD из файла .env для доступа к панели.</p><label>Пароль приложения<input type="password" autoFocus required value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label>{authError&&<p className="inline-error">{authError}</p>}<button className="btn primary full" disabled={busy} type="submit">{busy?<LoaderCircle className="spin" size={17}/>:<>Открыть панель <ArrowRight size={16}/></>}</button></form>}<p className="login-note"><ShieldCheck size={14}/>Ключи Tuya хранятся только на сервере</p></div></div>
  const demo=state?.preferences.mode==='demo'
  return <div className="app-shell">
    {mobile&&<div className="sidebar-scrim" onClick={()=>setMobile(false)}/>}
    <aside id="workspace-menu" ref={sidebarRef} aria-label="Разделы приложения" className={`sidebar ${mobile?'visible':''}`}><button className="icon-button sidebar-close" aria-label="Закрыть меню" onClick={()=>setMobile(false)}><X size={22}/></button><Brand/><div className="workspace-picker"><div className="home-glyph"><PlugZap size={19}/></div><div><strong>Мой умный дом</strong><small>Личное пространство</small></div><ChevronDown size={14}/></div><span className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</span><nav>{navigation.slice(0,7).map(n=><button key={n.id} className={page===n.id?'active':''} onClick={()=>navigate(n.id)}><n.icon size={18}/><span>{n.label}</span>{n.id==='devices'&&<small>{state?.devices.length||0}</small>}{n.id==='live'&&<i className="nav-live-dot"/>}</button>)}</nav><div className="sidebar-bottom"><div className="connection-card"><span className={`status-orb ${connection==='live'?'connected':''}`}/><div><strong>{connection==='live'?'Сервер подключён':'Восстанавливаем связь'}</strong><small>{connection==='live'?'Данные синхронизируются':'Автоматический повтор'}</small></div></div><nav><button className={page==='settings'?'active':''} onClick={()=>navigate('settings')}><Settings2 size={18}/>Настройки</button><button onClick={()=>{setMobile(false);setHelp(true)}}><CircleHelp size={18}/>Как это работает</button></nav><div className="sidebar-profile"><div className="avatar">МД</div><div><strong>Мой дом</strong><small>Personal workspace</small></div>{state?.cloud.password_enabled&&<button className="icon-button" title="Выйти" aria-label="Выйти" onClick={async()=>{await send('/auth/logout');setMobile(false);setAuth(false)}}><LogOut size={16}/></button>}</div></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Меню" aria-expanded={mobile} aria-controls="workspace-menu" onClick={()=>setMobile(true)}><Menu size={22}/></button><span>Рабочее пространство</span><span className="breadcrumb-divider">/</span><strong>{navigation.find(n=>n.id===page)?.label}</strong></div><div className="topbar-actions">{demo&&<Badge tone="amber"><FlaskConical size={12}/>DEMO MODE</Badge>}<div className="notification-wrap"><button className={`icon-button bell ${notifications?'selected':''}`} aria-label="Уведомления" onClick={()=>setNotifications(!notifications)}><Bell size={18}/>{state?.events.some(e=>e.kind==='completed')&&<i/>}</button>{notifications&&<div className="notification-popover card"><div className="section-heading"><h3>Журнал событий</h3><button className="icon-button" aria-label="Закрыть" onClick={()=>setNotifications(false)}><X size={16}/></button></div>{state?.events.length?state.events.slice(0,12).map(e=><div className="notification" key={e.id}><span className={`event-dot ${e.kind==='warning'||e.kind==='command_failed'?'warning':''}`}/><div><p>{e.message}</p><small>{date(e.at,state.preferences.timezone,true)}</small></div></div>):<Empty title="Пока тихо"/>}</div>}</div><div className="avatar small-avatar">МД</div></div></header>
      <main>{!state?<><div className="welcome"><h1>Подключаем ваш дом<span>…</span></h1></div>{error?<div className="inline-error">{error}<button className="btn subtle" onClick={refresh}>Повторить</button></div>:<Busy/>}</>:<>
        <div className="context-bar"><div className="context-source"><span className={`dot ${demo?'amber-dot':'green-dot'}`}/><span>{page==='connection'?'Диагностика Tuya Cloud · без команд реле':demo?'Демонстрация · все показания синтетические':'Tuya Cloud · реальные измерения'}</span></div>{page!=='connection'&&<label className="device-select"><PlugZap size={15}/><select aria-label="Текущее устройство" value={device?.id||''} onChange={e=>select(e.target.value)}>{state.devices.length?state.devices.map(d=><option key={d.id} value={d.id}>{d.name}</option>):<option value="">Нет устройств</option>}</select></label>}</div>
        {(error||statsError)&&<div className="inline-error">{error||statsError}</div>}{device?.error&&<div className="offline-banner"><Wifi size={16}/><span>{device.error} · Показаны последние доступные значения.</span></div>}
        {state.preferences.mode==='tuya'&&device&&!device.mapping.power&&['dashboard','analytics'].includes(page)&&<div className="offline-banner"><CircleHelp size={16}/><span>Модель не предоставляет настроенную мощность. Энергия и зарядные сеансы недоступны без реальных показаний. Проверьте возможности в Connection Setup.</span></div>}<AnimatePresence mode="wait"><motion.div key={page} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:.18}}>
          {page==='dashboard'&&<Dashboard state={state} device={device} stats={stats} period={period} setPeriod={setPeriod} navigate={navigate} run={run} busy={busy} now={now}/>}
          {page==='live'&&<Monitoring state={state} device={device} stats={stats} run={run} busy={busy} now={now}/>}
          {page==='history'&&<History key={device?.id+state.preferences.mode} state={state} device={device} revision={revision+Math.floor(state.server_time/10)}/>}
          {page==='analytics'&&<Analytics stats={stats} period={period} setPeriod={setPeriod} device={device}/>}
          {page==='automation'&&<Automation key={state.preferences.mode} state={state} device={device} run={run} revision={revision+Math.floor(state.server_time/10)} busy={busy}/>}
          {page==='devices'&&<Devices state={state} selected={device?.id||''} select={select} run={run} busy={busy}/>}
          {page==='connection'&&<ConnectionSetup state={state} run={run} busy={busy} revision={revision} select={select} navigate={navigate}/>}
          {page==='settings'&&<Settings key={JSON.stringify(state.preferences)} state={state} run={run} busy={busy}/>}
        </motion.div></AnimatePresence>
        <footer className="footer"><span>TUYA <i>/</i> POWER MONITOR</span><span><span className="dot green-dot"/> {connection==='live'?'WebSocket подключён':'Повтор подключения'}<b>·</b> {demo?'Demo environment':'Cloud environment'}</span><small>Сделано для осознанной энергии.</small></footer>
      </>}</main>
    </div>
    <nav className="phone-nav" aria-label="Быстрая навигация">
      {phoneNavigation.map(n=><button key={n.id} aria-current={page===n.id?'page':undefined} className={page===n.id&&!mobile?'active':''} onClick={()=>navigate(n.id)}><n.icon size={21}/><span>{n.label}</span></button>)}
      <button className={mobile||!phoneNavigation.some(n=>n.id===page)?'active':''} aria-label="Все разделы" aria-expanded={mobile} aria-controls="workspace-menu" onClick={()=>setMobile(!mobile)}><MoreHorizontal size={22}/><span>Ещё</span></button>
    </nav>
    <AnimatePresence>{toast&&<motion.div className={`toast ${toast.error?'error':''}`} role="status" initial={{opacity:0,y:20}} animate={{opacity:1,y:0}} exit={{opacity:0,y:15}}>{toast.error?<CircleHelp size={19}/>:<Check size={19}/>}<span>{toast.message}</span><button className="icon-button" onClick={()=>setToast(null)} aria-label="Закрыть"><X size={16}/></button></motion.div>}</AnimatePresence>
    {help&&<div className="modal-backdrop" onClick={()=>setHelp(false)}><section className="modal card" role="dialog" aria-modal="true" aria-label="Как это работает" onClick={e=>e.stopPropagation()}><div className="section-heading"><Brand/><button className="icon-button" aria-label="Закрыть" onClick={()=>setHelp(false)}><X size={20}/></button></div><h2>Управление энергией без догадок.</h2><p className="muted">1. В деморежиме включайте розетку и запускайте сценарии в Live Monitoring.</p><p className="muted">2. Детектор начинает сеанс при превышении порога и завершает после устойчивого снижения мощности.</p><p className="muted">3. Для настоящей розетки откройте Connection Setup, заполните .env, перезапустите сервер и выполните диагностику и безопасную активацию.</p><Note>Сервер должен оставаться включённым для выполнения автоматизаций. Приложение не получает процент аккумулятора или полные циклы батареи из умной розетки.</Note><button className="btn primary full" onClick={()=>setHelp(false)}>Понятно</button></section></div>}
  </div>
}
