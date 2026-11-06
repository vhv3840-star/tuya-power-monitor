import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './style.css'
import './connection.css'
import './phone.css'
import './light.css'

class ErrorBoundary extends React.Component<{children:React.ReactNode},{error:boolean}> {
  state = {error:false}
  static getDerivedStateFromError() {return {error:true}}
  render() {return this.state.error ? <div className="login-shell"><div className="card login-card"><h1>Не удалось отобразить страницу</h1><p>Данные остаются на сервере. Перезагрузите интерфейс.</p><button className="btn primary" onClick={()=>location.reload()}>Перезагрузить</button></div></div> : this.props.children}
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ErrorBoundary><App/></ErrorBoundary></React.StrictMode>)
