#!/usr/bin/python3
"""Battery Care: unprivileged per-app CPU/GPU activity counters.

Prints cumulative counters grouped by systemd unit (apps launched by the desktop
have their own scope). The panel turns successive samples into energy impact.
No privileges are needed. Files are written only to the private state
directory: the small laptop power model the panel learns on battery
(--save-model) and the 10-day usage history of 15-minute buckets (--add-history).
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import sys
import time

import battery

CGROUP = Path(os.environ.get('BATTERY_CARE_CGROUP_ROOT', '/sys/fs/cgroup'))
PROC = Path(os.environ.get('BATTERY_CARE_PROC_ROOT', '/proc'))
LAUNCHERS = {'gtk-launch', 'xdg-terminal-exec', 'uwsm-app', 'uwsm', 'app2unit', 'setsid', 'env', 'sh', 'bash'}
INTERPRETERS = re.compile(r'^(ba|z|da)?sh$|^python[0-9.]*$|^perl$|^node$|^ruby$')
HELPERS = {'chrome_crashpad_handler', 'chrome_crashpad', 'kitten', 'socat', 'sleep', 'cat'}
DESKTOPS = {'hyprland', 'gnome', 'kde', 'niri', 'sway', 'river'}
SERVICE_NAMES = {'init.scope': 'systemd'}
MAX_PROCS = 32
MODEL = 'power-model.json'
MODEL_KEYS = ('w', 'a', 'p', 'aa', 'ap')
HISTORY = 'history.json'
BUCKET = 900
RETENTION = 10 * 86400
BUCKET_APPS = 5
BUCKET_NUMBERS = ('seconds', 'battery', 'charged', 'wh', 'active')
KINDS = ('app', 'service', 'system')


def read_text(path, limit=65536):
    try:
        with open(path, 'rb') as handle:
            return handle.read(limit).decode('utf-8', 'replace')
    except OSError:
        return None


def unescape(name):
    return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), name)


def cpu_usage(directory):
    text = read_text(directory / 'cpu.stat', 4096) or ''
    match = re.search(r'^usage_usec (\d+)$', text, re.M)
    return int(match.group(1)) if match else None


def units():
    """Yield (relative cgroup path, unit name, kind) for each scope or service."""
    root = CGROUP
    stack = [(root, 'system')]
    while stack:
        directory, kind = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            name = entry.name
            path = Path(entry.path)
            if name.endswith('.slice'):
                stack.append((path, 'app' if name == 'app.slice' or kind == 'app' else
                              'service' if name.startswith('user-') or kind == 'service' else kind))
            elif re.match(r'^user@\d+\.service$', name):
                stack.append((path, 'service'))
            elif name.endswith(('.scope', '.service')):
                # Desktop apps are scopes or autostart services; other services are daemons.
                daemon = kind == 'app' and name.endswith('.service') and '@autostart' not in name
                yield '/' + str(path.relative_to(root)), name, 'service' if daemon else kind


def unit_id(name):
    """app-Hyprland-gtk\\x2dlaunch-554264c0.scope -> gtk-launch."""
    base = unescape(re.sub(r'\.(scope|service)$', '', name))
    if base.startswith('app-'):
        base = base[4:]
        current = {d.lower() for d in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':') if d}
        head, _, rest = base.partition('-')
        if rest and head.lower() in DESKTOPS | current:
            base = rest
    base = re.sub(r'@(autostart|[0-9a-f]{8,})$', '', base)
    return re.sub(r'(-[0-9]+)+$|-[0-9a-f]{8}$', '', base)


class DesktopIndex:
    """Application names from .desktop entries, looked up by id, executable, or URL."""

    def __init__(self, directories=None):
        self.ids, self.execs, self.urls = {}, {}, []
        languages = self.languages()
        for directory in directories if directories is not None else self.directories():
            try:
                files = sorted(Path(directory).glob('*.desktop'))
            except OSError:
                continue
            for path in files:
                entry = self.parse(path)
                if not entry:
                    continue
                name = next((entry[k] for k in [f'name[{l}]' for l in languages] + ['name'] if entry.get(k)), '')
                if not name:
                    continue
                for key in (path.stem.lower(), entry.get('startupwmclass', '').lower()):
                    if key:
                        self.ids.setdefault(key, name)
                command = entry.get('exec', '').split()
                if command:
                    self.execs.setdefault(os.path.basename(command[0]).lower(), name)
                for url in re.findall(r'https?://[^\s"\']+', entry.get('exec', '')):
                    self.urls.append((url.rstrip('/'), name))

    @staticmethod
    def directories():
        data_home = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share')
        dirs = [data_home] + (os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':')
        return [Path(d) / sub for d in dirs if d for sub in ('applications', 'wayland-sessions')]

    @staticmethod
    def languages():
        for variable in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
            value = os.environ.get(variable, '').split('.')[0].split('@')[0]
            if value and value not in ('C', 'POSIX'):
                return [value.lower(), value.split('_')[0].lower()]
        return []

    @staticmethod
    def parse(path):
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            parser.read_string(read_text(path) or '')
            section = parser['Desktop Entry']
        except (configparser.Error, KeyError):
            return None
        return {k.lower(): v.strip() for k, v in section.items()}

    def by_id(self, value):
        value = value.lower()
        return self.ids.get(value) or self.ids.get(value.rsplit('.', 1)[-1])

    def by_url(self, url):
        url = url.rstrip('/')
        return next((name for known, name in self.urls if known == url), None)


def process_name(pid, index):
    raw = read_text(PROC / str(pid) / 'cmdline', 8192)
    if not raw:
        return None
    argv = [a for a in raw.split('\0') if a]
    if not argv:
        return None
    exe = os.path.basename(argv[0]).split()[0]
    if INTERPRETERS.match(exe):
        script = next((a for a in argv[1:] if not a.startswith('-')), None)
        if script:
            exe = os.path.basename(script)
    app = next((a.split('=', 1)[1] for a in argv if a.startswith('--app=')), None)
    if app and index.by_url(app):
        return index.by_url(app)
    if app:
        host = re.sub(r'^https?://([^/:]+).*$', r'\1', app)
        return re.sub(r'^www\.', '', host)
    return index.by_id(exe) or index.execs.get(exe.lower()) or exe


def dominant_process(directory, index):
    """Name a launcher scope after the program most of its processes run."""
    procs = (read_text(directory / 'cgroup.procs') or '').split()[:MAX_PROCS]
    counts = {}
    for pid in procs:
        name = process_name(pid, index)
        if name and name not in HELPERS and name not in LAUNCHERS:
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=lambda n: (counts[n], -list(counts).index(n))) if counts else None


def display_name(directory, name, kind, index):
    if name in SERVICE_NAMES:
        return SERVICE_NAMES[name]
    ident = unit_id(name)
    if '@' in ident and ident.split('@', 1)[1].endswith('.desktop'):
        ident = ident.split('@', 1)[1][:-len('.desktop')]
    if ident not in LAUNCHERS:
        known = index.by_id(ident)
        if known:
            return known
        if kind != 'app' and name.endswith('.service'):
            return ident
    return dominant_process(directory, index) or ident


def gpu_usage(owners):
    """Sum DRM fdinfo engine counters per unit, counting each client once."""
    usage, seen, clock = {}, set(), None
    try:
        pids = [p for p in os.listdir(PROC) if p.isdigit()]
    except OSError:
        return usage, clock
    for pid in pids:
        cgroup = (read_text(PROC / pid / 'cgroup', 4096) or '').strip().rpartition('::')[2]
        owner = owners(cgroup)
        if owner is None:
            continue
        try:
            fds = os.listdir(PROC / pid / 'fdinfo')
        except OSError:
            continue
        for fd in fds:
            try:
                if not os.readlink(PROC / pid / 'fd' / fd).startswith('/dev/dri/'):
                    continue
            except OSError:
                continue
            info = read_text(PROC / pid / 'fdinfo' / fd, 8192) or ''
            fields = dict(re.findall(r'^(drm-[\w-]+):\s+(\d+)', info, re.M))
            device = re.search(r'^drm-pdev:\s+(\S+)', info, re.M)
            client = (device.group(1) if device else '', fields.get('drm-client-id'))
            if client[1] is None or client in seen:
                continue
            seen.add(client)
            entry = usage.setdefault(owner, {'gpuNs': 0, 'gpuCycles': 0})
            for key, value in fields.items():
                if key.startswith('drm-engine-') and not key.startswith('drm-engine-capacity-'):
                    entry['gpuNs'] += int(value)
                elif key.startswith('drm-cycles-'):
                    entry['gpuCycles'] += int(value)
                elif key.startswith('drm-total-cycles-'):
                    clock = max(clock or 0, int(value))
    return usage, clock


def sample(index=None):
    index = index or DesktopIndex()
    found = []
    for path, name, kind in units():
        directory = CGROUP / path.lstrip('/')
        cpu = cpu_usage(directory)
        if cpu is not None:
            found.append({'id': path, 'name': display_name(directory, name, kind, index),
                          'kind': kind, 'cpu': cpu, 'gpuNs': 0, 'gpuCycles': 0})
    known = {u['id']: u for u in found}

    def owner(cgroup):
        while cgroup and cgroup != '/':
            if cgroup in known:
                return cgroup
            cgroup = cgroup.rsplit('/', 1)[0]
        return None
    gpu, clock = gpu_usage(owner)
    for key, values in gpu.items():
        known[key].update(values)
    return {'time': time.monotonic(), 'gpuClock': clock, 'units': found}


def valid_model(model):
    if not isinstance(model, dict) or set(model) != set(MODEL_KEYS):
        return None
    for key in MODEL_KEYS:
        value = model[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e9:
            return None
    return {key: float(model[key]) for key in MODEL_KEYS}


def load_model():
    """The stored model, or None if absent or invalid; never blocks a sample."""
    try:
        with battery.safe_directory(battery.STATE, create=False) as directory_fd:
            raw = battery.read_owned(directory_fd, MODEL)
        return valid_model(json.loads(raw)) if raw else None
    except (OSError, ValueError, RuntimeError):
        return None


def save_model(raw):
    model = valid_model(json.loads(raw))
    if model is None:
        raise ValueError('Invalid power model')
    with battery.safe_directory(battery.STATE, private=True) as directory_fd:
        battery.publish_file(directory_fd, MODEL, json.dumps(model) + '\n', replace=True)


def number(value, high):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value <= high


def valid_bucket(bucket, now):
    """Strictly validated 15-minute bucket, or None."""
    keys = {'start', 'level', 'apps', *BUCKET_NUMBERS}
    if not isinstance(bucket, dict) or set(bucket) != keys:
        return None
    start = bucket['start']
    if (isinstance(start, bool) or not isinstance(start, int) or start % BUCKET
            or not now - RETENTION - BUCKET <= start <= now + BUCKET):
        return None
    if not all(number(bucket[k], 1e7) for k in BUCKET_NUMBERS):
        return None
    if bucket['level'] is not None and not number(bucket['level'], 100):
        return None
    apps = bucket['apps']
    if not isinstance(apps, list) or len(apps) > BUCKET_APPS:
        return None
    for app in apps:
        if (not isinstance(app, dict) or set(app) != {'name', 'kind', 'cores'}
                or not isinstance(app['name'], str) or not 0 < len(app['name']) <= 128
                or app['kind'] not in KINDS or not number(app['cores'], 1e7)):
            return None
    return {'start': start, 'level': bucket['level'], 'apps': [dict(a) for a in apps],
            **{k: float(bucket[k]) for k in BUCKET_NUMBERS}}


def merge(older, newer):
    """A shell restart within a bucket produces two partial buckets with one start."""
    result = {k: older[k] + newer[k] for k in BUCKET_NUMBERS}
    apps = {}
    for app in older['apps'] + newer['apps']:
        key = (app['kind'], app['name'])
        apps[key] = apps.get(key, 0) + app['cores']
    ranked = sorted(apps.items(), key=lambda item: (-item[1], item[0][1]))[:BUCKET_APPS]
    result.update(start=newer['start'], level=newer['level'] if newer['level'] is not None else older['level'],
                  apps=[{'name': name, 'kind': kind, 'cores': cores} for (kind, name), cores in ranked])
    return result


def load_history(now):
    """Stored buckets within retention; an absent or corrupt file reads as empty."""
    try:
        with battery.safe_directory(battery.STATE, create=False) as directory_fd:
            raw = battery.read_owned(directory_fd, HISTORY)
        data = json.loads(raw) if raw else {}
    except FileNotFoundError:
        return []
    except ValueError:
        return []
    buckets = data.get('buckets') if isinstance(data, dict) else None
    if not isinstance(buckets, list):
        return []
    return sorted((b for b in map(lambda b: valid_bucket(b, now), buckets) if b), key=lambda b: b['start'])


def add_history(raw, now=None):
    now = time.time() if now is None else now
    bucket = valid_bucket(json.loads(raw), now)
    if bucket is None:
        raise ValueError('Invalid history bucket')
    buckets = {b['start']: b for b in load_history(now)}
    existing = buckets.get(bucket['start'])
    buckets[bucket['start']] = merge(existing, bucket) if existing else bucket
    kept = sorted((b for b in buckets.values() if b['start'] >= now - RETENTION - BUCKET), key=lambda b: b['start'])
    with battery.safe_directory(battery.STATE, private=True) as directory_fd:
        battery.publish_file(directory_fd, HISTORY, json.dumps({'version': 1, 'buckets': kept}) + '\n', replace=True)
    return kept


def clear_history():
    """Remove only our own regular history file."""
    try:
        with battery.safe_directory(battery.STATE, create=False) as directory_fd:
            if battery.read_owned(directory_fd, HISTORY) is not None:
                os.unlink(HISTORY, dir_fd=directory_fd)
                os.fsync(directory_fd)
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument('--save-model', metavar='JSON')
    commands.add_argument('--add-history', metavar='JSON')
    commands.add_argument('--history', action='store_true')
    commands.add_argument('--clear-history', action='store_true')
    args = parser.parse_args()
    try:
        if args.save_model is not None:
            save_model(args.save_model)
            return 0
        if args.add_history is not None or args.history or args.clear_history:
            if args.clear_history:
                clear_history()
            buckets = add_history(args.add_history) if args.add_history is not None else load_history(time.time())
            print(json.dumps({'buckets': buckets}, allow_nan=False))
            return 0
        result = sample()
        result['model'] = load_model()
        print(json.dumps(result, allow_nan=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
