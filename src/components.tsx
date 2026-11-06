import type { ReactNode } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from 'recharts'
import { ArrowDownRight, ArrowUpRight, ArrowUpRight as External, CircleHelp, Inbox, LoaderCircle, Power, Zap } from 'lucide-react'
import type { Point } from './types'
import plugProduct from './assets/tuya-real-plug.png'

export const num = (n: number | null | undefined, digits = 1) => n == null ? '—' : n.toLocaleString('ru-RU', {maximumFractionDigits: digits, minimumFractionDigits: digits})
export const duration = (s: number) => {const m = Math.max(0, Math.floor(s / 60)); return m >= 60 ? `${Math.floor(m / 60)} ч ${m % 60} мин` : m ? `${m} мин` : `${Math.max(0, Math.floor(s))} сек`}
export const date = (at: number, tz: string, full = false) => new Date(at * 1000).toLocaleString('ru-RU', {timeZone: tz, day: full ? '2-digit' : undefined, month: full ? 'short' : undefined, hour:'2-digit', minute:'2-digit', second: full ? undefined : '2-digit'})
export function Badge({children, tone = ''}: {children: ReactNode; tone?: string}) {return <span className={`badge ${tone}`}>{children}</span>}
export function Toggle({on, onChange, label, disabled = false}: {on: boolean; onChange: () => void; label: string; disabled?: boolean}) {return <button type="button" className={`toggle ${on ? 'on' : ''}`} role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={onChange}><span/></button>}
export function Empty({title = 'Пока нет данных', children}: {title?: string; children?: ReactNode}) {return <div className="empty"><Inbox size={30}/><h3>{title}</h3><p>{children || 'Новые данные появятся после следующего опроса устройства.'}</p></div>}
export function Busy() {return <div className="loading"><LoaderCircle className="spin" size={23}/><span>Загружаем данные…</span></div>}
export function SectionTitle({eyebrow, title, children}: {eyebrow?: string; title:string; children?:ReactNode}) {return <div className="section-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>{children}</div>}
export function Metric({label, value, unit, icon, change, note, accent = ''}: {label: string; value: string; unit?: string; icon:ReactNode; change?:number | null; note?:string; accent?:string}) {return <div className={`metric card ${accent}`}><div className="metric-head"><span>{label}</span><span className="metric-icon">{icon}</span></div><div className="metric-value">{value}<small>{unit}</small></div><div className="metric-foot">{change != null ? <><span className={change <= 0 ? 'positive' : 'blue-text'}>{change <= 0 ? <ArrowDownRight size={13}/> : <ArrowUpRight size={13}/>} {num(Math.abs(change))}%</span><span>к прошлому периоду</span></> : <span>{note || 'По данным розетки'}</span>}</div></div>}
export function EnergyChart({data, field = 'power', bars = false, color = '#2679ee', height = 260}: {data: Point[]; field?: 'power'|'energy'|'voltage'|'current'; bars?:boolean; color?:string; height?:number}) {
  if (!data.length) return <Empty/>
  const unit = {power:'Вт',energy:'кВт·ч',voltage:'В',current:'А'}[field]
  const content = <><CartesianGrid vertical={false} stroke="#e6edf6" strokeDasharray="3 5"/><XAxis dataKey="label" axisLine={false} tickLine={false} minTickGap={36} tick={{fill:'#8090a5',fontSize:11}} dy={10}/><YAxis axisLine={false} tickLine={false} width={43} tick={{fill:'#8090a5',fontSize:11}} tickFormatter={v => num(Number(v), field==='energy' ? 2 : 0)}/><Tooltip content={({active,payload,label}) => active && payload?.length ? <div className="chart-tooltip"><span>{label}</span><strong>{num(Number(payload[0].value),field==='energy'?4:2)} <small>{unit}</small></strong></div> : null}/></>
  return <div className="chart-box" style={{height}}><ResponsiveContainer width="100%" height="100%">{bars ? <BarChart data={data} margin={{top:12,right:10,bottom:12,left:0}}>{content}<Bar dataKey={field} fill={color} opacity={.85} radius={[5,5,0,0]} maxBarSize={38}/></BarChart> : <AreaChart data={data} margin={{top:12,right:10,bottom:12,left:0}}><defs><linearGradient id={`fill-${field}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={.25}/><stop offset="100%" stopColor={color} stopOpacity={0}/></linearGradient></defs>{content}<Area type="monotone" dataKey={field} stroke={color} strokeWidth={2} fill={`url(#fill-${field})`} connectNulls={false} animationDuration={500} dot={false}/></AreaChart>}</ResponsiveContainer></div>
}
export function PlugIllustration({on}: {on:boolean}) {
  return <img
    className="plug-art plug-product"
    src={plugProduct}
    alt="Умная розетка Tuya с боковой кнопкой и европейской вилкой"
    width={240}
    height={240}
    decoding="async"
    draggable={false}
    data-power={on?'on':'off'}
  />
}
export function PowerButton({on, disabled, pending, onClick}: {on:boolean;disabled?:boolean;pending?:boolean;onClick:()=>void}) {return <button className={`power-button ${on?'active':''}`} disabled={disabled||pending} onClick={onClick} aria-label={on?'Выключить розетку':'Включить розетку'}>{pending?<LoaderCircle size={27} className="spin"/>:<Power size={28}/>}</button>}
export function Note({children}: {children:ReactNode}) {return <div className="note"><CircleHelp size={16}/><span>{children}</span></div>}
export function LinkButton({children, onClick}: {children:ReactNode;onClick:()=>void}) {return <button className="text-button" onClick={onClick}>{children}<External size={16}/></button>}
export function Brand() {return <div className="brand"><span className="brand-icon"><Zap size={24} fill="currentColor"/></span><div><strong>TUYA<span> / </span></strong><small>POWER MONITOR</small></div></div>}
