#!/usr/bin/python3
"""Battery Care preferences; Omarchy remains responsible for idle and locking."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import battery

KEY = 'batteryCare'


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'omarchy/shell.json'


def pair(value):
    if not isinstance(value, dict):
        raise ValueError('Screen and lock settings must contain two timeouts.')
    result = {}
    for key in ('screensaver', 'lock'):
        seconds = value.get(key)
        if type(seconds) is not int or not 0 <= seconds <= 86400:
            raise ValueError('Choose a timeout up to 24 hours (zero means immediately, never disabled).')
        result[key] = seconds
    return result


def current_pair(config):
    idle = config.get('idle', {})
    if not isinstance(idle, dict):
        raise ValueError('Omarchy idle configuration is invalid.')
    # Preserve zero as Omarchy's immediate action, never as disabled/Never.
    result = {k: idle.get(k, default) for k, default in [('screensaver', 150), ('lock', 300)]}
    if any(type(v) is not int or not 0 <= v <= 86400 for v in result.values()):
        raise ValueError('Existing Omarchy idle timeouts are outside the supported range.')
    return result


def preferences(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1 or type(value.get('separate')) is not bool:
        raise ValueError('Screen and lock preferences are invalid.')
    return dict(version=1, separate=value['separate'],
                **{key: pair(value.get(key)) for key in ('shared', 'battery', 'ac')})


def read_config(fd):
    raw = battery.read_owned(fd, 'shell.json')
    if raw is None:
        raise RuntimeError('Omarchy shell.json is missing. Create it through Omarchy before editing timeouts.')
    config = json.loads(raw)
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('Omarchy shell.json is invalid; no settings were changed.')
    current_pair(config)
    return raw, config


def config_preferences(config):
    existing = config.get('idle', {}).get(KEY)
    if existing is not None:
        return preferences(existing)
    active = current_pair(config)
    return dict(version=1, separate=False, shared=dict(active), battery=dict(active), ac=dict(active))


def revision(config):
    # Changes elsewhere in shell.json do not invalidate a draft; they are merged
    # by reading the latest file at Apply. Idle edits must be explicitly reloaded.
    return hashlib.sha256(json.dumps(config.get('idle', {}), sort_keys=True).encode()).hexdigest()


def source():
    return 'battery' if battery.UPower().on_battery() else 'ac'


def runtime():
    def query(*args):
        response = subprocess.run(['omarchy-shell', *args], check=True, capture_output=True,
                                  text=True, timeout=5)
        return json.loads(response.stdout)
    state = query('idle', 'status')
    locked = query('lock', 'isLocked')
    if (not isinstance(state, dict) or type(locked) is not bool
            or any(type(state.get(k)) is not bool for k in ('idle', 'inIdleCycle', 'stayAwake'))):
        raise RuntimeError('Omarchy did not return a valid idle status.')
    return state, locked


def desired(prefs, power):
    return prefs[power if prefs['separate'] else 'shared']


def externally_changed(config):
    saved = config.get('idle', {}).get(KEY)
    return saved is not None and saved.get('lastApplied') != current_pair(config)


def safe_to_switch(state, locked):
    return not (locked or state['idle'] or state['inIdleCycle']
                or state.get('screensaverStarted') or state.get('processes', {}).get('lock'))


def snapshot(config, power, state, locked, warning=''):
    prefs = config_preferences(config)
    return dict(preferences=prefs, revision=revision(config), source=power,
                active=current_pair(config), managed=KEY in config.get('idle', {}),
                pending=desired(prefs, power) != current_pair(config),
                externalChange=externally_changed(config), stayAwake=state.get('stayAwake', False),
                safeToSwitch=safe_to_switch(state, locked), warning=warning)


def write_config(fd, raw, config, *, backup):
    # All Battery Care writers share its verified state lock. Other Omarchy
    # writers do not, so detect intervening changes and never use a stale copy.
    if battery.read_owned(fd, 'shell.json') != raw:
        raise RuntimeError('Omarchy settings changed while saving. Reload and try again.')
    if backup:
        with battery.safe_directory(battery.STATE, private=True) as state_fd:
            battery.publish_file(state_fd, 'idle-shell-before-' + str(time.time_ns()) + '.json', raw)
    if battery.read_owned(fd, 'shell.json') != raw:
        raise RuntimeError('Omarchy settings changed while saving. Reload and try again.')
    battery.publish_file(fd, 'shell.json', json.dumps(config, indent=2) + '\n', replace=True)


def operate(action, payload=None, expected=None, active=False, active_at=None):
    if action not in ('status', 'apply', 'sync'):
        raise ValueError('Unknown idle action')
    # Slow shell IPC must never hold up charge recovery or a charge action.
    with battery.locked('idle-lock'), battery.safe_directory(config_path().parent, create=False) as fd:
        raw, config = read_config(fd)
        power = source()
        try:
            state, locked = runtime()
            warning = ''
        except Exception as error:
            if action != 'status':
                raise RuntimeError('Could not verify Omarchy idle state; settings were not changed. ' + str(error)) from error
            state, locked = dict(idle=True, inIdleCycle=True, stayAwake=False), True
            warning = 'Omarchy idle status is unavailable.'
        if action == 'status':
            return snapshot(config, power, state, locked, warning)
        updated = copy.deepcopy(config)
        idle = updated.setdefault('idle', {})
        if action == 'apply':
            if expected != revision(config):
                raise RuntimeError('Screen and lock settings changed elsewhere. Reload settings before applying your edits.')
            prefs = preferences(payload)
            idle[KEY] = dict(prefs, lastApplied=current_pair(config))
        else:
            if KEY not in idle:
                return snapshot(config, power, state, locked)
            if externally_changed(config):
                raise RuntimeError('Timeouts changed outside Battery Care. Open Screen & lock and apply or reload your settings.')
            prefs = config_preferences(config)
        # The UI's one-second activity monitor also gates this path. Never change
        # the stock service's timer intervals during an existing idle cycle.
        if active and safe_to_switch(state, locked):
            # Recheck after lock acquisition and parsing. Activity evidence from
            # an older UI request is not permission to restart idle intervals.
            state, locked = runtime()
            active = (active_at is not None and 0 <= time.time() * 1000 - active_at <= 1000)
        if active and safe_to_switch(state, locked):
            idle.update(desired(prefs, power))
            idle[KEY]['lastApplied'] = desired(prefs, power)
        if updated != config:
            write_config(fd, raw, updated, backup=action == 'apply')
        return snapshot(updated, power, state, locked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'apply', 'sync'])
    parser.add_argument('--preferences')
    parser.add_argument('--revision')
    parser.add_argument('--active', action='store_true')
    parser.add_argument('--active-at', type=float)
    args = parser.parse_args()
    try:
        print(json.dumps(operate(args.action, json.loads(args.preferences) if args.preferences else None,
                                 args.revision, args.active, args.active_at)))
        return 0
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
