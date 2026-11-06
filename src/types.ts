export type Mode = 'demo' | 'tuya'
export type Page = 'dashboard' | 'live' | 'history' | 'analytics' | 'automation' | 'devices' | 'connection' | 'settings'
export interface Preferences { mode: Mode; tariff: number; start_w: number; start_hold_s: number; end_w: number; hold_s: number; timezone: string; notifications: boolean }
export interface SchemaItem { code: string; type: string; values?: string | Record<string, unknown>; name?: string }
export interface Device { id: string; name: string; mode: Mode; mapping: Record<string,string>; schema: {functions?: SchemaItem[]; status?: SchemaItem[]}; relay: boolean | null; online: boolean; power?: number | null; voltage?: number | null; current?: number | null; energy?: number | null; updated_at?: number; error?: string; session_started?: number | null; session_energy?: number; low_since?: number | null }
export interface Event { id: number; at: number; kind: string; message: string }
export interface MonitorState {preferences: Preferences; server_time: number; devices: Device[]; events: Event[]; cloud: {configured: boolean; region: string; password_enabled: boolean; poll_seconds: number}}
export interface Point {label: string; at: number; energy?: number | null; power: number | null; voltage?: number | null; current?: number | null; cost?: number | null}
export interface Stats {energy: number | null; previous_energy: number | null; cost: number | null; change: number | null; sessions: number; average_duration: number; peak: number | null; chart: Point[]; live_chart: Point[]; mode: Mode; energy_source: string; period_days: number;power_observed:boolean}
export interface Charge {id: number; device_id: string; mode: Mode; started: number; ended: number | null; duration: number; energy: number; cost: number; average: number; peak: number; status: string}
export interface Rule {id: number; device_id: string; name: string; kind: string; enabled: boolean; config: {minutes: number; threshold: number; hold_s: number; start: string; end: string}; due_at: number | null; last_run: string | null}
export type Run = (action: () => Promise<unknown>, success?: string) => Promise<boolean>
export interface ConnectionDevice {
  id:string;name:string;online:boolean;schema:{functions?:SchemaItem[];status?:SchemaItem[]};mapping:Record<string,string>;
  readings:{power?:number|null;voltage?:number|null;current?:number|null;energy?:number|null;relay?:boolean|null};
  points:{code:string;type:string;scale:number|null;unit:string|null;raw_value:unknown;writable:boolean}[];
  command_ready:boolean;energy_supported:boolean;status_readable:boolean;errors:{message:string;code:string;hint:string}[]
}
export interface ConnectionReport {
  checked_at:number|null;region:string;endpoint:string;stale:boolean;
  configuration:{password:boolean;client_id:boolean;client_secret:boolean;device_source:boolean};
  steps:{id:string;title:string;status:'pass'|'fail'|'warning';message:string;code?:string;hint?:string|null}[];
  devices:ConnectionDevice[];
  physical_verification:{status:string;tests:Record<string,{on?:{confirmed_at:number;reported_relay:boolean};off?:{confirmed_at:number;reported_relay:boolean}}>}
}
