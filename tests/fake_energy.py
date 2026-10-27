"""Deterministic energy.py substitute for the isolated QML review harness."""
import json
import time
now = time.monotonic()
print(json.dumps({'time': now, 'gpuClock': None, 'units': [
    {'id': '/app.slice/app-test.scope', 'name': 'Test app', 'kind': 'app', 'cpu': int(now * 4e5), 'gpuNs': 0, 'gpuCycles': 0}]}))
