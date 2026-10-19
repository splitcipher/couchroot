"""Read the S89C's public identity API before preparing a firmware profile."""
import argparse
import http.client
import ipaddress
import json
import sys

from .common import Refused


def inspect(host):
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as error:
        raise Refused('Enter the TV\'s private IPv4 address.') from error
    if not address.is_private or address.is_loopback or address.is_unspecified:
        raise Refused('Enter the TV\'s private IPv4 address.')

    connection = http.client.HTTPConnection(str(address), 8001, timeout=5)
    try:
        connection.request('GET', '/api/v2/')
        response = connection.getresponse()
        if response.status != 200:
            raise Refused('TV identity request returned HTTP ' + str(response.status))
        body = response.read(65537)
        if len(body) > 65536:
            raise Refused('TV identity response exceeds 64 KiB.')
    except (OSError, http.client.HTTPException) as error:
        raise Refused('TV request failed; check its address, power and network connection.') from error
    finally:
        connection.close()

    try:
        payload = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeError) as error:
        raise Refused('TV identity response is invalid JSON.') from error
    device = payload.get('device') if isinstance(payload, dict) else None
    if not isinstance(device, dict):
        raise Refused('TV identity response is missing its device object.')
    if device.get('modelName') != 'QN77S89CBFXZA':
        raise Refused('Expected model QN77S89CBFXZA; this response identifies another model.')
    if not isinstance(device.get('model'), str) or not device['model'].strip():
        raise Refused('TV identity response is missing its platform identifier.')
    fields = ('modelName', 'model', 'OS', 'developerMode', 'developerIP')
    for field in fields:
        value = device.get(field)
        types = (str, int) if field == 'developerMode' else (str,)
        if value is not None and not isinstance(value, types):
            raise Refused('TV identity response has an invalid ' + field + ' field.')
    return {
        'device': {field: device.get(field) for field in fields},
        'setup_supported': False,
        'remaining_checks': 'Firmware, runtime, Home routing, startup and recovery require on-TV inspection.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='TV private IPv4 address; performs one GET on port 8001')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(args.host), indent=2))
        return 0
    except Refused as error:
        print('s89c-inspect: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
