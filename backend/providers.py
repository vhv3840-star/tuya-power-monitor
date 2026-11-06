"""Official Tuya OpenAPI adapter; all codes are validated against device schema."""
import asyncio
import hashlib
import hmac
import json
import math
import time
from urllib.parse import quote
import httpx

REGIONS = {
    'eu': 'https://openapi.tuyaeu.com', 'us': 'https://openapi.tuyaus.com',
    'cn': 'https://openapi.tuyacn.com', 'in': 'https://openapi.tuyain.com',
    'we': 'https://openapi-weaz.tuyaeu.com', 'ea': 'https://openapi-ueaz.tuyaus.com',
    'sg': 'https://openapi-sg.iotbing.com',
}


class ProviderError(Exception):
    def __init__(self, message, *, code='provider_error', hint='Проверьте соединение и настройки проекта Tuya.'):
        super().__init__(message)
        self.code, self.hint = code, hint


ERROR_HELP = {
    '1004': ('Неверная подпись запроса', 'Сверьте Access ID и Access Secret одного cloud-проекта, TUYA_REGION и часы компьютера.'),
    '1010': ('Токен недействителен', 'Повторите диагностику: сервер запросит новый токен. Проверьте Access ID/Secret и регион.'),
    '1011': ('Токен истёк', 'Повторите диагностику для обновления токена.'),
    '1012': ('Токен недействителен', 'Перезапустите проверку авторизации и проверьте ключи проекта.'),
    '1106': ('Нет доступа к устройству', 'В Devices → Link Tuya App Account привяжите Smart Life по QR-коду. Сверьте UID, Device ID и дата-центр аккаунта.'),
    '28841002': ('Подписка cloud-проекта истекла', 'Проверьте срок плана IoT Core в Tuya Cloud.'),
    '28841004': ('Квота cloud-проекта исчерпана', 'Проверьте квоту Tuya и увеличьте интервал TUYA_POLL_SECONDS.'),
    '28841101': ('API не подключён', 'Подключите API в Tuya Cloud → Service API и авторизуйте проект.'),
    '28841102': ('Подписка API истекла', 'Проверьте срок подписки необходимого API в Tuya Cloud.'),
    '28841104': ('Квота API исчерпана', 'Проверьте лимиты API; уменьшите частоту опроса.'),
    '28841105': ('Проект не авторизован для API', 'В Service API предоставьте cloud-проекту доступ к необходимым API, включая токен, устройства, схему, status и commands.'),
    '28841106': ('Нет подписки на API', 'В Service API подключите пакет, предоставляющий этот API.'),
}


def decode_readings(statuses, schema, mapping):
    raw = {s['code']: s.get('value') for s in statuses if isinstance(s, dict) and 'code' in s}
    definitions = {s['code']: s for s in schema.get('status', [])}
    result = {kind: normalize_metric(raw.get(mapping.get(kind)), definitions.get(mapping.get(kind), {}), kind)
              for kind in ('power', 'voltage', 'current', 'energy')}
    relay = raw.get(mapping.get('switch'))
    result['relay'] = relay if isinstance(relay, bool) else None
    return result


def signed_headers(client_id, secret, method, path, body='', token='', timestamp=None):
    stamp = timestamp or str(int(time.time() * 1000))
    to_sign = method.upper() + '\n' + hashlib.sha256(body.encode()).hexdigest() + '\n\n' + path
    sign = hmac.new(secret.encode(), (client_id + token + stamp + to_sign).encode(), hashlib.sha256).hexdigest().upper()
    return {'client_id': client_id, 'access_token': token, 't': stamp, 'sign': sign,
            'sign_method': 'HMAC-SHA256', 'Content-Type': 'application/json'}


def properties(item):
    value = item.get('values', {})
    try:
        return json.loads(value) if isinstance(value, str) else value or {}
    except (ValueError, TypeError):
        return {}


def normalize_metric(raw, schema, metric):
    if isinstance(raw, bool) or not isinstance(raw, (float, int)):
        return None
    values = properties(schema)
    unit = str(values.get('unit', '')).strip().lower()
    factors = {'power': {'w': 1, 'kw': 1000}, 'voltage': {'v': 1, 'mv': .001},
               'current': {'a': 1, 'ma': .001}, 'energy': {'kwh': 1, 'wh': .001}}
    factor = factors.get(metric, {}).get(unit)
    if factor is None:
        return None
    try:
        scale = int(values.get('scale', 0))
        if not -12 <= scale <= 12:
            return None
        value = float(raw) / 10 ** scale * factor
    except (ValueError, TypeError, OverflowError):
        return None
    return round(value, 6) if math.isfinite(value) and value >= 0 else None


def discover_mapping(schema):
    result = {}
    functions = schema.get('functions', [])
    for code in ('switch_1', 'switch'):
        if any(f.get('code') == code and f.get('type', '').lower() in ('bool', 'boolean') for f in functions):
            result['switch'] = code
            break
    aliases = {'power': ('cur_power', 'power'), 'voltage': ('cur_voltage', 'voltage'),
               'current': ('cur_current', 'current'), 'energy': ('add_ele', 'total_forward_energy', 'energy')}
    for metric, candidates in aliases.items():
        for code in candidates:
            item = next((s for s in schema.get('status', []) if s.get('code') == code), None)
            if item and normalize_metric(0, item, metric) is not None:
                result[metric] = code
                break
    return result


class TuyaProvider:
    def __init__(self, settings):
        self.settings = settings
        self.http = httpx.AsyncClient(base_url=REGIONS[settings.region], timeout=15)
        self.token, self.expires = '', 0
        self.lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    async def _call(self, method, path, data=None, token=''):
        body = json.dumps(data, separators=(',', ':'), ensure_ascii=False) if data is not None else ''
        headers = signed_headers(self.settings.client_id, self.settings.client_secret, method, path, body, token)
        try:
            response = await self.http.request(method, path, content=body.encode(), headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            code = f'http_{exc.response.status_code}'
            raise ProviderError(f'Tuya Cloud: HTTP {exc.response.status_code}', code=code,
                                hint='Проверьте TUYA_REGION, доступ к интернету и API cloud-проекта.') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError('Tuya Cloud недоступен или вернул некорректный JSON.', code='network_error',
                                hint='Проверьте интернет, proxy/VPN, часы компьютера и TUYA_REGION. Повторите диагностику.') from exc
        if not isinstance(payload, dict):
            raise ProviderError('Tuya вернул неожиданный формат ответа.', code='invalid_response')
        if not payload.get('success'):
            raw_code = str(payload.get('code', 'unknown'))
            code = raw_code if raw_code.isdigit() and len(raw_code)<=20 else 'unknown'
            if code in ('1010', '1011', '1012'):
                self.expires = 0
            # Never echo arbitrary provider bodies, which may contain credentials.
            title, hint = ERROR_HELP.get(code, ('Ошибка Tuya API', 'Проверьте код в Tuya API Explorer и права cloud-проекта. Ответы и секреты не публикуйте.'))
            raise ProviderError(f'Tuya {code}: {title}.', code=code, hint=hint)
        return payload.get('result')

    async def authenticate(self):
        if not self.settings.client_id or not self.settings.client_secret:
            raise ProviderError('Ключи Tuya не заданы.', code='missing_credentials', hint='Заполните TUYA_CLIENT_ID и TUYA_CLIENT_SECRET в .env и перезапустите сервер.')
        async with self.lock:
            if time.time() >= self.expires:
                result = await self._call('GET', '/v1.0/token?grant_type=1')
                if not isinstance(result, dict) or not isinstance(result.get('access_token'), str) or not result.get('expire_time'):
                    raise ProviderError('Tuya не вернул корректный токен.', code='invalid_token_response')
                self.token = result['access_token']
                self.expires = time.time() + int(result['expire_time']) - 60
        return True

    async def request(self, method, path, data=None):
        await self.authenticate()
        return await self._call(method, path, data, self.token)

    async def devices(self):
        if not self.settings.client_id or not self.settings.client_secret:
            raise ProviderError('Укажите TUYA_CLIENT_ID и TUYA_CLIENT_SECRET в .env и перезапустите сервер.')
        if self.settings.uid:
            items = await self.request('GET', '/v1.0/users/' + quote(self.settings.uid, safe='') + '/devices')
        else:
            if not self.settings.device_ids:
                raise ProviderError('Укажите TUYA_UID или TUYA_DEVICE_IDS в .env.')
            items = [await self.request('GET', '/v1.0/devices/' + quote(i, safe='')) for i in self.settings.device_ids]
        if not isinstance(items, list):
            raise ProviderError('Tuya вернул неожиданный список устройств.')
        return items

    async def schema(self, device_id):
        return await self.request('GET', f'/v1.0/iot-03/devices/{quote(device_id, safe="")}/specification')

    async def status(self, device_id):
        did = quote(device_id, safe='')
        info = await self.request('GET', f'/v1.0/devices/{did}')
        if not info.get('online', False):
            raise ProviderError('Розетка не в сети. Последние значения сохранены.', code='device_offline',
                                hint='Проверьте питание, Wi-Fi и статус Online в Smart Life. Реле автоматически не переключается.')
        result = await self.request('GET', f'/v1.0/iot-03/devices/{did}/status')
        if not isinstance(result, list):
            raise ProviderError('Tuya вернул некорректный status устройства.', code='invalid_status')
        return result

    async def confirm_relay(self, device_id, code, on, *, attempts=3, delay=1):
        """Only report success after Tuya's Boolean status matches the requested relay."""
        last_error = None
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(delay)
            try:
                statuses = await self.status(device_id)
                value = next((s.get('value') for s in statuses if s.get('code') == code), None)
                if isinstance(value, bool) and value is on:
                    return statuses
            except ProviderError as exc:
                last_error = exc
        suffix = f' Последняя ошибка: {last_error}.' if last_error else ''
        raise ProviderError('Состояние реле не подтверждено после команды.' + suffix, code='state_unconfirmed',
                            hint='Команда могла выполниться. Проверьте розетку в Smart Life и обновите состояние; не повторяйте переключение вслепую.')

    async def command(self, device_id, code, value):
        result = await self.request('POST', f'/v1.0/iot-03/devices/{quote(device_id, safe="")}/commands',
                                    {'commands': [{'code': code, 'value': value}]})
        if result is not True:
            raise ProviderError('Tuya не подтвердил команду.')
