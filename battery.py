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
import secrets
import stat
import subprocess
import sys
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


@contextlib.contextmanager
def safe_directory(path, *, private=False, create=True):
    """Pin directories by descriptor; never follow symlinks in managed paths."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise RuntimeError('Battery Care requires an absolute, normalized directory: ' + str(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            # A sticky shared ancestor (e.g. /tmp in tests) protects owned entries.
            if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise RuntimeError('Unsafe writable directory in Battery Care path: ' + str(path))
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise RuntimeError('Battery Care directory is not owned by this user: ' + str(path))
        if private:
            os.fchmod(fd, 0o700)
        elif info.st_mode & 0o022:
            raise RuntimeError('Unsafe writable Battery Care directory: ' + str(path))
        yield fd
    finally:
        os.close(fd)


def verify_file(fd, name):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or info.st_mode & 0o022):
        raise RuntimeError('Refusing unsafe or unowned Battery Care file: ' + name)
    return info


def read_owned(directory_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with contextlib.ExitStack() as stack:
        stack.callback(os.close, fd)
        info = verify_file(fd, name)
        if info.st_size > 1024 * 1024:
            raise RuntimeError('Battery Care file is unexpectedly large: ' + name)
        # Bound the read even if another process grows the file after fstat.
        data = os.read(fd, 1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError('Battery Care file is unexpectedly large: ' + name)
        return data.decode('utf-8')


def publish_file(directory_fd, name, data, *, replace=False):
    """Publish a flushed private file. Unit creation must never clobber a name."""
    temp = '.battery-care-' + secrets.token_hex(16)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            # Also reject unexpected existing state files, rather than erase them.
            read_owned(directory_fd, name)
            os.replace(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        else:
            os.link(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False)
            os.unlink(temp, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temp, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def read_state():
    with safe_directory(STATE, private=True) as directory_fd:
        raw = read_owned(directory_fd, 'state.json')
        if raw is None:
            return {'batteries': {}}
        state = json.loads(raw)
        if not isinstance(state, dict) or not isinstance(state.get('batteries', {}), dict):
            raise ValueError('Invalid battery-care state')
        for key, record in state.get('batteries', {}).items():
            if (not isinstance(record, dict) or record.get('mode') not in ('protect', 'full', 'off', '')
                    or not isinstance(record.get('boot'), str)):
                raise ValueError('Invalid battery-care recovery record for ' + key)
        return state


def save_state(state):
    # Flush both the contents and rename before any charging change can follow.
    with safe_directory(STATE, private=True) as directory_fd:
        publish_file(directory_fd, 'state.json', json.dumps(state, indent=2) + '\n', replace=True)


@contextlib.contextmanager
def locked():
    with safe_directory(STATE, private=True) as directory_fd, contextlib.ExitStack() as stack:
        fd = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=directory_fd)
        stack.callback(os.close, fd)
        verify_file(fd, 'lock')
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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


def unit_directory():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'


def guard_files():
    script = str(Path(__file__).resolve()).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$')
    service = '[Unit]\nDescription=Restore Battery Care charge protection\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 "' + script + '" reconcile\n'
    timer = '[Unit]\nDescription=Check temporary full-charge sessions\n\n[Timer]\nOnStartupSec=5s\nOnUnitActiveSec=15s\nAccuracySec=1s\n\n[Install]\nWantedBy=timers.target\n'
    # Exact contents recognize 0.2.0 units too; a marker alone is not ownership.
    return {UNIT + '.service': service, UNIT + '.timer': timer}


def check_guard_files(directory_fd):
    present = []
    for name, expected in guard_files().items():
        actual = read_owned(directory_fd, name)
        if actual is not None:
            if actual != expected:
                raise RuntimeError('Refusing foreign or modified recovery unit: ' + name
                                   + '. Resolve this file conflict before retrying.')
            present.append(name)
    return present


def install_guard():
    """Explicit actions only. Reuse verified units; never overwrite existing files."""
    with safe_directory(unit_directory()) as directory_fd:
        present = check_guard_files(directory_fd)  # Preflight both before writing either.
        for name, data in guard_files().items():
            if name not in present:
                publish_file(directory_fd, name, data)
        check_guard_files(directory_fd)
    run('systemctl', '--user', 'daemon-reload')
    run('systemctl', '--user', 'enable', '--now', UNIT + '.timer')
    run('systemctl', '--user', 'is-active', '--quiet', UNIT + '.timer')


@contextlib.contextmanager
def checked_guard_directory():
    with contextlib.ExitStack() as stack:
        try:
            fd = stack.enter_context(safe_directory(unit_directory(), create=False))
        except FileNotFoundError:
            yield None
            return
        check_guard_files(fd)
        yield fd


def remove_guard(directory_fd):
    if directory_fd is None:
        return
    present = check_guard_files(directory_fd)
    if not present:
        return
    if UNIT + '.timer' in present:
        run('systemctl', '--user', 'disable', '--now', UNIT + '.timer')
    # Recheck after systemctl, and only unlink our exact regular unit files.
    for name in check_guard_files(directory_fd):
        os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)
    run('systemctl', '--user', 'daemon-reload')


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
            except (ValueError, OSError, RuntimeError) as error:
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
                with checked_guard_directory() as directory_fd:
                    prepare_release(api, state, api.devices())
                    remove_guard(directory_fd)
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
