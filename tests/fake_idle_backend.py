#!/usr/bin/python3
"""Real config backend with isolated config/state and simulated desktop state."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import idle_settings as idle

fixture = Path(os.environ['BATTERY_CARE_IDLE_TEST_STATE'])
assert str(fixture).startswith('/tmp/battery-care-qml.')
assert str(idle.config_path()).startswith(str(fixture.parent) + '/')
assert str(idle.battery.STATE).startswith(str(fixture.parent) + '/')

if sys.argv[1] in ('test-ac-idle', 'test-ac-active', 'test-status-error'):
    fixture.write_text(json.dumps({'source': 'unknown' if sys.argv[1] == 'test-status-error' else 'ac', 'idle': sys.argv[1] == 'test-ac-idle'}))
    sys.exit(0)

def fixture_data():
    return json.loads(fixture.read_text()) if fixture.exists() else dict(source='battery', idle=False)

idle.source = lambda: fixture_data()['source']
idle.runtime = lambda: (dict(idle=fixture_data()['idle'], inIdleCycle=fixture_data()['idle'], stayAwake=False), False)
sys.exit(idle.main())
