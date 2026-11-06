import { Cable, Activity, ArrowRight, BatteryCharging, Clock3, Coins, Gauge, Leaf, LoaderCircle, Power, Radio, ShieldCheck, Timer, Wifi, Zap } from 'lucide-react'
import { Badge, date, duration, EnergyChart, LinkButton, Metric, Note, num, PlugIllustration, SectionTitle } from '../components'
import { send } from '../api'
import type { Device, MonitorState, Page, Run, Stats } from '../types'

interface Props {state:MonitorState; device?:Device; stats:Stats|null; period:string; setPeriod:(v:string)=>void; navigate:(p:Page)=>void; run:Run; busy:boolean; now:number}
export default function Dashboard({state,device,stats,period,setPeriod,navigate,run,busy,now}:Props) {
  const demo = state.preferences.mode === 'demo'
  const on = device?.relay === true
  const elapsed = device?.session_started ? now - device.session_started : 0
  const control = (next:boolean) => device && run(()=>send(`/api/devices/${device.id}/relay`,{on:next}),next?'Розетка включена':'Розетка выключена')
  return <div className="dashboard-page">
    <div className="welcome"><div><div className="eyebrow"><span className="tiny-line"/> УМНЫЙ ДОМ · ЭНЕРГИЯ ПОД КОНТРОЛЕМ</div><h1>Обзор энергии<span>.</span></h1><p>Меньше лишнего. Больше контроля над каждым ваттом.</p></div><div className="welcome-date"><span>{new Date(now*1000).toLocaleDateString('ru-RU',{timeZone:state.preferences.timezone,day:'numeric',month:'long',weekday:'long'})}</span><Badge tone={device?.online?'green':''}><span className="dot"/>{device?.online?'Система онлайн':'Ожидание устройства'}</Badge></div></div>
    {demo&&<div className="setup-cta"><Cable size={19}/><div><strong>Подключите вашу физическую розетку Smart Life</strong><p>Пошаговая настройка Cloud и диагностика реального устройства.</p></div><button className="btn subtle" onClick={()=>navigate('connection')}>Подключить розетку <ArrowRight size={15}/></button></div>}<div className="metric-grid">
      <Metric label="Текущая мощность" value={num(device?.power)} unit="Вт" icon={<Zap size={18}/>} note={device?.online?'Обновляется в реальном времени':'Последнее доступное значение'} accent="featured"/>
      <Metric label="Потребление" value={num(stats?.energy,3)} unit="кВт·ч" icon={<Activity size={18}/>} change={stats?.change} note="Расчёт по мощности за период"/>
      <Metric label="Стоимость энергии" value={num(stats?.cost,2)} unit="₸" icon={<Coins size={18}/>} note={`Тариф ${num(state.preferences.tariff,2)} ₸ / кВт·ч`}/>
      <Metric label="Сеансы зарядки" value={num(stats?.sessions,0)} icon={<BatteryCharging size={18}/>} note={`Среднее время · ${duration(stats?.average_duration||0)}`}/>
    </div>
    <div className="dashboard-main dashboard-phone">
      <section className="card consumption"><SectionTitle eyebrow="ENERGY OVERVIEW" title="Потребление энергии"><div className="segmented">{[['day','24 часа'],['week','7 дней'],['month','30 дней']].map(([v,l])=><button key={v} className={v===period?'selected':''} onClick={()=>setPeriod(v)}>{l}</button>)}</div></SectionTitle><div className="chart-summary"><strong>{num(stats?.energy,3)} <small>кВт·ч</small></strong><span className="chart-legend"><i/> Расчётное потребление</span></div>{stats?<EnergyChart data={stats.chart} field="energy" height={244}/>:<div className="chart-skeleton"/>}<div className="chart-footer"><span><Leaf size={14}/> Каждый ватт имеет значение</span><LinkButton onClick={()=>navigate('analytics')}>Вся аналитика</LinkButton></div></section>
      <section className="card device-hero">
        <div className="hero-heading"><span className="eyebrow">ВАША УМНАЯ РОЗЕТКА</span><Badge tone={on?'green':''}>{device?.relay==null?'НЕИЗВЕСТНО':on?'ВКЛЮЧЕНА':'ВЫКЛЮЧЕНА'}</Badge></div>
        <div className="plug-scene"><div className={`orbit orbit-one ${on?'lit':''}`}/><div className="orbit orbit-two"/><PlugIllustration on={on}/><span className="floating-chip"><Wifi size={13}/> Wi-Fi</span></div>
        <div className="device-title"><div><h2>{device?.name||'Нет устройств'}</h2><p>{demo?'Tuya Smart Plug · Демонстрация':'Tuya Smart Plug · Cloud API'}</p></div></div>
        <div className="device-power-summary"><span><Zap size={15}/>Текущая мощность</span><strong>{num(device?.power)}<small>Вт</small></strong></div>
        <div className="relay-actions" role="group" aria-label="Питание розетки">
          {[true,false].map(next=><button key={String(next)} className={`relay-action ${device?.relay===next?'selected':''}`} aria-label={next?'Включить розетку':'Выключить розетку'} aria-pressed={device?.relay===next} disabled={busy||!device?.online||!device?.mapping.switch} onClick={()=>control(next)}>{busy?<LoaderCircle className="spin"/>:<Power/>}<span>{next?'ВКЛ':'ВЫКЛ'}</span></button>)}
        </div>
        <div className="device-bottom"><span><span className={`dot ${device?.online?'green-dot':''}`}/>{device?.online?'Подключено':'Нет соединения'}</span><button className="text-button" onClick={()=>navigate('devices')}>Подробнее <ArrowRight size={14}/></button></div>
        <button className="timer-shortcut" onClick={()=>navigate('automation')}><Timer/><span><strong>Таймер и сценарии</strong><small>Настройте автоматическое отключение</small></span><ArrowRight size={17}/></button>
      </section>
    </div>
    <div className="dashboard-bottom">
      <section className="card charging-card"><SectionTitle title="Текущий сеанс"><Badge tone={device?.session_started?'green':''}>{device?.session_started?'Зарядка идёт':'Ожидание'}</Badge></SectionTitle><div className="session-row"><div className="session-icon"><BatteryCharging size={29}/></div><div><h3>{device?.session_started?'Устройство заряжается':'Готовы к следующей зарядке'}</h3><p>{device?.low_since?'Подтверждаем низкую мощность…':device?.session_started?'Начало определено по мощности':'Сеанс начнётся автоматически'}</p></div></div><div className="session-stats"><div><Clock3 size={15}/><strong>{duration(elapsed)}</strong><small>Длительность</small></div><div><Zap size={15}/><strong>{num(device?.session_energy||0,4)} <em>кВт·ч</em></strong><small>{num((device?.session_energy||0)*1000,2)} Wh · расчёт</small></div><div><Coins size={15}/><strong>{num((device?.session_energy||0)*state.preferences.tariff,2)} <em>₸</em></strong><small>Стоимость</small></div></div><Note>Розетка измеряет мощность. Процент аккумулятора и полные циклы батареи недоступны.</Note></section>
      <section className="card electrical"><SectionTitle title="Состояние сети"><Gauge size={18}/></SectionTitle><div className="electrical-item"><span><Activity size={16}/> Напряжение</span><strong>{num(device?.voltage)} <small>В</small></strong></div><div className="electrical-item"><span><Zap size={16}/> Сила тока</span><strong>{num(device?.current,3)} <small>А</small></strong></div><div className="electrical-item"><span><Radio size={16}/> Обновлено</span><strong className="small-value">{device?.updated_at?date(device.updated_at,state.preferences.timezone):'—'}</strong></div><div className="network-note"><ShieldCheck size={15}/><span>{demo?'Изолированный деморежим':'Секреты остаются на сервере'}</span></div></section>
    </div>
    <section className="automation-banner"><div className="banner-icon"><Timer size={23}/></div><div><h3>Умная зарядка. Без лишних забот.</h3><p>Таймеры, ночной режим и отключение по мощности работают на сервере.</p></div><button className="btn subtle" onClick={()=>navigate('automation')}>Настроить автоматизацию <ArrowRight size={16}/></button></section>
  </div>
}
