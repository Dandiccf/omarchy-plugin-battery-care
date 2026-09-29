import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('battery', Path(__file__).resolve().parents[1] / 'battery.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class FakeUPower:
    def __init__(self):
        self.calls = []
        self.failure = False
        self.device = dict(key='bat0', native='BAT0', ChargeThresholdSupported=True,
                           ChargeThresholdEnabled=False, ChargeStartThreshold=75,
                           ChargeEndThreshold=80, actualEnd=100, EnergyFull=59,
                           EnergyFullDesign=58)

    def enable(self, device, enabled):
        self.calls.append((device['key'], enabled))
        # Recovery must already be durable when we lift the limit.
        assert b.read_state()['batteries'][device['key']]
        if self.failure:
            raise RuntimeError('permission denied')
        device['ChargeThresholdEnabled'] = enabled
        device['actualEnd'] = 80 if enabled else 100

    def devices(self): return [self.device]
    def on_battery(self): return False


class BatteryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(b, 'STATE', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = FakeUPower()
        self.state = {'batteries': {}}

    def full(self):
        b.apply_action(self.api, self.state, self.api.device, 'full', 'boot1', False)


class RecoveryTests(BatteryFixture):
    def test_status_does_not_confuse_preset_with_active_cap(self):
        d = b.snapshot(self.api, self.state)['batteries'][0]
        self.assertFalse(d['enabled'])
        self.assertEqual((d['end'], d['actualEnd']), (80, 100))
        self.assertFalse(d['mismatch'])

    def test_full_stays_until_unplug_then_restores(self):
        self.full()
        b.reconcile(self.api, self.state, self.api.devices(), 'boot1', False)
        self.assertEqual(self.api.calls, [('bat0', False)])
        b.reconcile(self.api, self.state, self.api.devices(), 'boot1', True)
        self.assertTrue(self.api.device['ChargeThresholdEnabled'])
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'protect')

    def test_reboot_restores_even_when_plugged_in(self):
        self.full()
        b.reconcile(self.api, b.read_state(), self.api.devices(), 'boot2', False)
        self.assertEqual(self.api.calls[-1], ('bat0', True))

    def test_failed_restore_retains_intention_and_retries(self):
        self.full()
        self.api.failure = True
        b.reconcile(self.api, self.state, self.api.devices(), 'boot1', True)
        self.assertEqual(b.read_state()['batteries']['bat0']['error'], 'permission denied')
        self.api.failure = False
        b.reconcile(self.api, b.read_state(), self.api.devices(), 'boot1', False)
        self.assertTrue(self.api.device['ChargeThresholdEnabled'])
        self.assertNotIn('error', b.read_state()['batteries']['bat0'])

    def test_cancel_full_restores_immediately(self):
        self.full()
        b.apply_action(self.api, self.state, self.api.device, 'protect', 'boot1', False)
        self.assertTrue(self.api.device['ChargeThresholdEnabled'])

    def test_off_stays_off_across_unplug_replug_and_reboot(self):
        b.apply_action(self.api, self.state, self.api.device, 'protect', 'boot1', False)
        b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', False)
        for boot, on_battery in [('boot1', True), ('boot1', False), ('boot2', False)]:
            b.reconcile(self.api, b.read_state(), self.api.devices(), boot, on_battery)
        self.assertFalse(self.api.device['ChargeThresholdEnabled'])
        self.assertEqual(self.api.device['actualEnd'], 100)
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'off')
        self.assertEqual(self.api.calls, [('bat0', True), ('bat0', False)])

    def test_off_cancels_temporary_full_charge_recovery(self):
        self.full()
        b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', False)
        b.reconcile(self.api, b.read_state(), self.api.devices(), 'boot2', True)
        self.assertFalse(self.api.device['ChargeThresholdEnabled'])

    def test_can_enable_protection_again_after_off(self):
        b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', True)
        b.apply_action(self.api, self.state, self.api.device, 'protect', 'boot1', True)
        self.assertTrue(self.api.device['ChargeThresholdEnabled'])
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'protect')

    def test_failed_off_keeps_previous_protection_intention(self):
        b.apply_action(self.api, self.state, self.api.device, 'protect', 'boot1', False)
        self.api.failure = True
        with self.assertRaises(RuntimeError):
            b.apply_action(self.api, self.state, self.api.device, 'off', 'boot1', False)
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'protect')
        self.assertIn('error', b.read_state()['batteries']['bat0'])

    def test_replaced_or_other_battery_is_not_modified(self):
        self.full()
        other = copy.copy(self.api.device)
        other['key'] = 'replacement'
        b.reconcile(self.api, self.state, [other], 'boot2', True)
        self.assertEqual(self.api.calls, [('bat0', False)])

    def test_full_refuses_on_battery(self):
        with self.assertRaisesRegex(RuntimeError, 'Connect'):
            b.apply_action(self.api, self.state, self.api.device, 'full', 'boot1', True)
        self.assertFalse(self.api.calls)
        self.assertFalse(b.read_state()['batteries'])

    def test_unsupported_refuses(self):
        self.api.device['ChargeThresholdSupported'] = False
        with self.assertRaisesRegex(RuntimeError, 'support'):
            self.full()
        self.assertFalse(self.api.calls)

    def test_failed_action_keeps_recovery_record(self):
        self.api.failure = True
        with self.assertRaises(RuntimeError): self.full()
        self.assertIn('bat0', b.read_state()['batteries'])

    def test_missing_health_and_unknown_preset(self):
        self.api.device['EnergyFullDesign'] = 0
        self.api.device['ChargeEndThreshold'] = 4294967295
        d = b.snapshot(self.api, self.state)['batteries'][0]
        self.assertIsNone(d['health'])
        self.assertIsNone(d['end'])

    def test_external_manager_mismatch_is_visible(self):
        self.api.device['ChargeThresholdEnabled'] = True
        self.assertTrue(b.snapshot(self.api, self.state)['batteries'][0]['mismatch'])


if __name__ == '__main__': unittest.main()
