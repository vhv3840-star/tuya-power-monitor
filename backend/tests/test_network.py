from types import SimpleNamespace
import pytest
from scripts import network


@pytest.mark.parametrize('password,secure_cookie,message', [
    ('', False, 'APP_PASSWORD'),
    ('set-password', True, 'HTTPS'),
])
def test_network_refuses_unprotected_http(monkeypatch,password,secure_cookie,message):
    monkeypatch.setattr(network.sys,'argv',['network.py','--check'])
    monkeypatch.setattr(network,'Config',lambda:SimpleNamespace(password=password,secure_cookie=secure_cookie))
    with pytest.raises(ValueError,match=message):
        network.main()


def test_network_origin_is_exact_and_keeps_existing_origins(monkeypatch,capsys):
    config=SimpleNamespace(password='set-password',secure_cookie=False,
                           allowed_origins=['http://127.0.0.1:8000'])
    monkeypatch.setattr(network.sys,'argv',['network.py','--check'])
    monkeypatch.setattr(network,'Config',lambda:config)
    monkeypatch.setattr(network,'local_address',lambda:'192.168.1.42')
    network.main()
    assert config.allowed_origins==['http://127.0.0.1:8000','http://192.168.1.42:8000']
    network.main()
    assert len(config.allowed_origins)==2
    output=capsys.readouterr().out
    assert 'http://192.168.1.42:8000/#dashboard' in output
    assert 'set-password' not in output
