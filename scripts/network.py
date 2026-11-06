"""Start the password-protected dashboard for devices on the same LAN."""
import argparse
import ipaddress
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Config


def local_address():
    # UDP connect chooses the default interface without sending application data.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(('192.0.2.1', 9))
            address = sock.getsockname()[0]
        except OSError:
            address = socket.gethostbyname(socket.gethostname())
    ip = ipaddress.ip_address(address)
    if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        raise ValueError('No private LAN address found. Connect this computer to Wi-Fi first.')
    return address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Show the phone URL without starting the server')
    args = parser.parse_args()
    config = Config()
    if not config.password:
        raise ValueError('Set APP_PASSWORD in .env before enabling phone access.')
    if config.secure_cookie:
        raise ValueError('COOKIE_SECURE=true requires HTTPS. Use your HTTPS deployment for phone access.')
    address = local_address()
    url = f'http://{address}:8000'
    if url not in config.allowed_origins:
        config.allowed_origins.append(url)
    print(f'\nPhone URL: {url}/#dashboard', flush=True)
    print('Connect the phone to the same Wi-Fi and sign in with your app password.', flush=True)
    print('The computer must remain on. Use a trusted home network.', flush=True)
    print('No router ports or Windows Firewall rules are changed. See MOBILE.md.\n', flush=True)
    if args.check:
        return
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(('127.0.0.1', 8000)) == 0:
            raise ValueError('Stop the Start.cmd server before starting Network.cmd.')
    from backend.main import create_app
    import uvicorn
    uvicorn.run(create_app(config), host='0.0.0.0', port=8000, workers=1)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f'Network start failed: {exc}', file=sys.stderr)
        sys.exit(1)
