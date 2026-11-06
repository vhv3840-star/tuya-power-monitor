import hashlib
import hmac
from backend.providers import signed_headers, normalize_metric, discover_mapping


def test_signature_signs_exact_body_and_path():
    body = '{"commands":[{"code":"relay","value":true}]}'
    path = '/v1.0/iot-03/devices/abc/commands'
    string = 'POST\n' + hashlib.sha256(body.encode()).hexdigest() + '\n\n' + path
    expected = hmac.new(b'secret', ('id' + 'token' + '123' + string).encode(), hashlib.sha256).hexdigest().upper()
    assert signed_headers('id', 'secret', 'POST', path, body, 'token', '123')['sign'] == expected


def test_scale_and_unit_conversion():
    assert normalize_metric(2301, {'values': '{"scale":1,"unit":"V"}'}, 'voltage') == 230.1
    assert normalize_metric(320, {'values': '{"scale":0,"unit":"mA"}'}, 'current') == .32
    assert normalize_metric(450, {'values': '{"scale":1,"unit":"W"}'}, 'power') == 45
    assert normalize_metric(42, {'values': '{"scale":0,"unit":"mystery"}'}, 'power') is None


def test_discovery_does_not_invent_codes():
    schema = {'functions': [{'code': 'indicator', 'type': 'Boolean'}], 'status': []}
    assert discover_mapping(schema) == {}
    schema['functions'].append({'code': 'switch_1', 'type': 'Boolean'})
    assert discover_mapping(schema)['switch'] == 'switch_1'


def test_invalid_schema_scale_is_unsupported():
    assert normalize_metric(50, {'values': '{"unit":"W","scale":"bad"}'}, 'power') is None
