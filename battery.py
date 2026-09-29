#!/usr/bin/python3
"""Battery Care: UPower telemetry and recoverable, per-battery full-charge sessions."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'omarchy-battery-care'
BUS = 'org.freedesktop.UPower'
IFACE = BUS + '.Device'
ROOT = '/org/freedesktop/UPower'
UNIT = 'omarchy-battery-care'


class UPower:
    def __init__(self, interactive=False):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.interactive = interactive

    def call(self, path, interface, method, signature=None, args=()):
        params = self.GLib.Variant(signature, args) if signature else None
        return self.bus.call_sync(BUS, path, interface, method, params, None,
                                 (self.Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION
                                  if self.interactive else self.Gio.DBusCallFlags.NONE),
                                 15000, None).unpack()

    def props(self, path, interface):
        return self.call(path, 'org.freedesktop.DBus.Properties', 'GetAll', '(s)', (interface,))[0]

    def devices(self):
        result = []
        for path in self.call(ROOT, BUS, 'EnumerateDevices')[0]:
            p = self.props(path, IFACE)
            if p.get('Type') == 2 and p.get('PowerSupply') and p.get('IsPresent'):
                native = Path(p.get('NativePath', '')).name
                p['path'] = path
                p['native'] = native
                p['key'] = hashlib.sha256((native + '\0' + p.get('Model', '') + '\0' + p.get('Serial', '')).encode()).hexdigest()[:24]
                p['actualStart'] = read_number(Path('/sys/class/power_supply') / native / 'charge_control_start_threshold')
                p['actualEnd'] = read_number(Path('/sys/class/power_supply') / native / 'charge_control_end_threshold')
                result.append(p)
        return result

    def on_battery(self):
        return self.props(ROOT, BUS)['OnBattery']

    def enable(self, device, enabled):
        self.call(device['path'], IFACE, 'EnableChargeThreshold', '(b)', (enabled,))
        p = self.props(device['path'], IFACE)
        if p.get('ChargeThresholdEnabled') != enabled:
            raise RuntimeError('UPower did not confirm the requested charge setting.')


def read_number(path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def read_state():
    try:
        state = json.loads((STATE / 'state.json').read_text())
        if not isinstance(state, dict) or not isinstance(state.get('batteries', {}), dict):
            raise ValueError('Invalid battery-care state')
        for key, record in state.get('batteries', {}).items():
            if (not isinstance(record, dict) or record.get('mode') not in ('protect', 'full', 'off', '')
                    or not isinstance(record.get('boot'), str)):
                raise ValueError('Invalid battery-care recovery record for ' + key)
        return state
    except FileNotFoundError:
        return {'batteries': {}}


def save_state(state):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Flush both the contents and rename before any charging change can follow.
    with tempfile.NamedTemporaryFile(mode='w', dir=STATE, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(json.dumps(state, indent=2) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
            temp.replace(STATE / 'state.json')
            directory_fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temp.unlink(missing_ok=True)


@contextlib.contextmanager
def locked():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('w') as handle:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another battery action is still running. Try again shortly.')
                time.sleep(0.05)
        yield


def run(*args):
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=25)
    except subprocess.CalledProcessError as error:
        raise RuntimeError((error.stderr or error.stdout or str(error)).strip()) from error


def install_guard():
    """Called only by an explicit protection/full-charge action, never a status read."""
    directory = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
    directory.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve()).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$')
    service = '[Unit]\nDescription=Restore Battery Care charge protection\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 "' + script + '" reconcile\n'
    timer = '[Unit]\nDescription=Check temporary full-charge sessions\n\n[Timer]\nOnStartupSec=5s\nOnUnitActiveSec=15s\nAccuracySec=1s\n\n[Install]\nWantedBy=timers.target\n'
    for suffix, data in [('service', service), ('timer', timer)]:
        target = directory / (UNIT + '.' + suffix)
        if not target.exists() or target.read_text() != data:
            target.write_text(data)
    run('systemctl', '--user', 'daemon-reload')
    run('systemctl', '--user', 'enable', '--now', UNIT + '.timer')
    run('systemctl', '--user', 'is-active', '--quiet', UNIT + '.timer')


def apply_action(api, state, device, action, boot, on_battery):
    if action not in ('protect', 'full', 'off'):
        raise ValueError('Unknown charge action')
    if not device.get('ChargeThresholdSupported'):
        raise RuntimeError('This battery does not support UPower charge limits.')
    if action == 'full' and on_battery:
        raise RuntimeError('Connect the charger before starting a full-charge session.')
    records = state.setdefault('batteries', {})
    # Save the recovery intention BEFORE disabling protection. Interrupted actions
    # therefore still restore the cap after unplugging or the next login/boot.
    previous = records.get(device['key'])
    records[device['key']] = {'mode': action, 'boot': boot}
    save_state(state)
    try:
        api.enable(device, action == 'protect')
        records[device['key']].pop('error', None)
    except Exception as error:
        if action == 'off':
            records[device['key']] = dict(previous or {'mode': '', 'boot': boot})
        records[device['key']]['error'] = str(error)
        raise
    finally:
        save_state(state)


def reconcile(api, state, devices, boot, on_battery):
    before = json.dumps(state, sort_keys=True)
    for device in devices:
        record = state.get('batteries', {}).get(device['key'])
        if not record:
            continue
        if record['mode'] == 'full' and (on_battery or record.get('boot') != boot):
            record['mode'] = 'protect'
        if record['mode'] == 'protect':
            try:
                if not device.get('ChargeThresholdEnabled'):
                    api.enable(device, True)
                record.pop('error', None)
            except Exception as error:
                record['error'] = str(error)
    if json.dumps(state, sort_keys=True) != before:
        save_state(state)


def number(value, default=None):
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else default


def thresholds_disagree(device, enabled, start, end):
    actual_end = device.get('actualEnd')
    actual_start = device.get('actualStart')
    if enabled:
        return ((end is not None and actual_end is not None and end != actual_end)
                or (start is not None and actual_start is not None and start != actual_start))
    return actual_end is not None and 0 < actual_end < 100


def guard_warning(state):
    if not any(r.get('mode') in ('protect', 'full') for r in state.get('batteries', {}).values()):
        return ''
    try:
        subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT + '.timer'],
                       check=True, capture_output=True, timeout=3)
    except Exception:
        return 'Automatic recovery is not running. Enable protection again to repair it.'
    return ''


def prepare_release(api, state, devices):
    """Restore temporary sessions, preserving an explicit Off choice."""
    available = {d['key'] for d in devices}
    pending = [key for key, r in state.get('batteries', {}).items()
               if r.get('mode') == 'full' and key not in available]
    if pending:
        raise RuntimeError('A battery with a temporary full-charge session is absent. Reconnect it before removing the guard.')
    for device in devices:
        record = state.get('batteries', {}).get(device['key'], {})
        if record.get('mode') in ('protect', 'full'):
            if not device.get('ChargeThresholdEnabled'):
                api.enable(device, True)


def snapshot(api, state):
    batteries = []
    for d in api.devices():
        record = state.get('batteries', {}).get(d['key'], {})
        enabled = bool(d.get('ChargeThresholdEnabled'))
        end = d.get('ChargeEndThreshold')
        start = d.get('ChargeStartThreshold')
        end = end if isinstance(end, int) and 0 < end <= 100 else None
        start = start if isinstance(start, int) and 0 <= start <= 100 else None
        actual_end = d.get('actualEnd')
        mismatch = thresholds_disagree(d, enabled, start, end)
        full = number(d.get('EnergyFull'))
        design = number(d.get('EnergyFullDesign'))
        batteries.append({
            'key': d['key'], 'native': d['native'], 'model': d.get('Model', ''),
            'percentage': number(d.get('Percentage')), 'state': d.get('State', 0),
            'rate': number(d.get('EnergyRate')), 'energy': number(d.get('Energy')),
            'full': full, 'design': design,
            'health': (100 * full / design) if full is not None and design and design > 0 else None,
            'cycles': number(d.get('ChargeCycles'), -1), 'timeToEmpty': number(d.get('TimeToEmpty'), 0),
            'timeToFull': number(d.get('TimeToFull'), 0), 'supported': bool(d.get('ChargeThresholdSupported')),
            'enabled': enabled, 'start': start, 'end': end, 'actualStart': d.get('actualStart'), 'actualEnd': actual_end,
            'mismatch': mismatch, 'mode': record.get('mode', ''), 'error': record.get('error', '')
        })
    return {'batteries': batteries, 'onBattery': api.on_battery()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'protect', 'full', 'off', 'reconcile', 'release'])
    parser.add_argument('--battery', default='')
    args = parser.parse_args()
    try:
        api = UPower(interactive=args.action in ('protect', 'full', 'off', 'release'))
        with locked():
            try:
                state = read_state()
            except (ValueError, OSError) as error:
                if args.action != 'status':
                    raise
                data = snapshot(api, {'batteries': {}})
                data['stateError'] = 'Recovery state could not be read: ' + str(error)
                print(json.dumps(data, allow_nan=False))
                return 0
            if args.action == 'reconcile':
                reconcile(api, state, api.devices(), boot_id(), api.on_battery())
                return 0
            elif args.action in ('protect', 'full', 'off'):
                devices = api.devices()
                device = next((d for d in devices if d['key'] == args.battery), None)
                if device is None:
                    raise RuntimeError('Battery is no longer available; refresh and try again.')
                if not device.get('ChargeThresholdSupported'):
                    raise RuntimeError('Charge limits are not supported for this battery.')
                if args.action == 'full' and api.on_battery():
                    raise RuntimeError('Connect the charger before starting a full-charge session.')
                if args.action != 'off':
                    install_guard()
                apply_action(api, state, device, args.action, boot_id(), api.on_battery())
            elif args.action == 'release':
                prepare_release(api, state, api.devices())
                unit_dir = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
                if (unit_dir / (UNIT + '.timer')).exists():
                    run('systemctl', '--user', 'disable', '--now', UNIT + '.timer')
                save_state({'batteries': {}})
            current = read_state()
            data = snapshot(api, current)
            data['guardWarning'] = guard_warning(current)
            print(json.dumps(data, allow_nan=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
