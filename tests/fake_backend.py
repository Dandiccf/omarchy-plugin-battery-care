"""Deterministic UPower substitute for the isolated QML review harness."""
import json
import sys
import os
from pathlib import Path
state = Path(os.environ['BATTERY_CARE_TEST_STATE'])
mode = {'protect': 'protect', 'full': 'full', 'off': 'off'}.get(sys.argv[1], state.read_text() if state.exists() else 'protect')
state.write_text(mode)
print(json.dumps({'batteries': [{'key': 'test', 'native': 'BAT0', 'model': 'Test battery', 'percentage': 50,
    'state': 1, 'supported': True, 'enabled': mode == 'protect', 'mode': mode, 'mismatch': False,
    'start': 75, 'end': 80, 'actualEnd': 80 if mode == 'protect' else 100,
    'health': 100, 'rate': 10, 'cycles': 2, 'full': 58, 'error': ''}], 'onBattery': False}))
