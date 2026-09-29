"""Failure and lifecycle cases found during the complete review."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from test_battery import BatteryFixture, b


class ReviewTests(BatteryFixture):
    def test_disabled_with_hardware_limit_is_a_mismatch(self):
        self.api.device['actualEnd'] = 80
        self.assertTrue(b.snapshot(self.api, self.state)['batteries'][0]['mismatch'])

    def test_start_threshold_mismatch(self):
        self.api.device.update(ChargeThresholdEnabled=True, actualEnd=80, actualStart=90)
        self.assertTrue(b.snapshot(self.api, self.state)['batteries'][0]['mismatch'])

    def test_missing_readings_are_not_fabricated_as_zero(self):
        self.api.device.update(EnergyRate=float('nan'), Percentage=float('inf'))
        result = b.snapshot(self.api, self.state)
        self.assertIsNone(result['batteries'][0]['percentage'])
        self.assertIsNone(result['batteries'][0]['rate'])
        json.dumps(result, allow_nan=False)

    def test_releasing_explicit_off_does_not_enable_protection(self):
        b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', False)
        self.api.calls.clear()
        b.prepare_release(self.api, self.state, self.api.devices())
        self.assertFalse(self.api.calls)
        self.assertFalse(self.api.device['ChargeThresholdEnabled'])

    def test_release_restores_temporary_full_session(self):
        self.full()
        b.prepare_release(self.api, self.state, self.api.devices())
        self.assertEqual(self.api.calls[-1], ('bat0', True))

    def test_absent_full_battery_blocks_guard_removal(self):
        self.full()
        with self.assertRaisesRegex(RuntimeError, 'absent'):
            b.prepare_release(self.api, self.state, [])
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'full')

    def test_failed_release_keeps_recovery_state(self):
        self.full()
        self.api.failure = True
        with self.assertRaises(RuntimeError):
            b.prepare_release(self.api, self.state, self.api.devices())
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'full')

    def test_malformed_record_rejected_without_overwriting_it(self):
        raw = '{"batteries":{"bat0":[]}}'
        (b.STATE / 'state.json').write_text(raw)
        with self.assertRaises(ValueError): b.read_state()
        self.assertEqual((b.STATE / 'state.json').read_text(), raw)

    def test_corrupt_state_still_allows_monitoring(self):
        (b.STATE / 'state.json').write_text('corrupt')
        output = io.StringIO()
        with patch.object(b, 'UPower', return_value=self.api), patch('sys.argv', ['battery.py', 'status']), contextlib.redirect_stdout(output):
            self.assertEqual(b.main(), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(len(data['batteries']), 1)
        self.assertIn('stateError', data)
        self.assertEqual((b.STATE / 'state.json').read_text(), 'corrupt')

    def test_failed_durable_save_prevents_charge_mutation(self):
        with patch.object(b.os, 'fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.full()
        self.assertFalse(self.api.calls)
        self.assertFalse((b.STATE / 'state.json').exists())

    def test_status_warns_when_guard_stopped(self):
        self.full()
        with patch.object(b.subprocess, 'run', side_effect=subprocess.CalledProcessError(3, 'systemctl')):
            self.assertIn('not running', b.guard_warning(self.state))

    def test_unmanaged_or_explicit_off_needs_no_guard(self):
        b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', True)
        with patch.object(b.subprocess, 'run') as run:
            self.assertEqual(b.guard_warning(self.state), '')
            run.assert_not_called()

    def test_guard_does_not_write_unchanged_state(self):
        b.apply_action(self.api, self.state, self.api.device, 'protect', 'boot1', False)
        with patch.object(b, 'save_state') as save:
            b.reconcile(self.api, self.state, self.api.devices(), 'boot1', False)
            save.assert_not_called()

    def test_release_without_installed_timer_is_idempotent(self):
        output = io.StringIO()
        with patch.object(b, 'UPower', return_value=self.api), patch('sys.argv', ['battery.py', 'release']), patch.dict(b.os.environ, {'XDG_CONFIG_HOME': str(b.STATE / 'config')}), patch.object(b, 'run') as run, contextlib.redirect_stdout(output):
            self.assertEqual(b.main(), 0)
            self.assertEqual(b.main(), 0)
            run.assert_not_called()
