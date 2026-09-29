import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import idle_settings as idle


class IdleSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config_dir = self.base / 'config/omarchy'
        self.config_dir.mkdir(parents=True)
        self.file = self.config_dir / 'shell.json'
        self.config = {'version': 1, 'idle': {'screensaver': 150, 'lock': 300, 'unrelated': True},
                       'bar': {'layout': {'right': [{'id': 'other-widget'}]}}, 'plugins': []}
        self.file.write_text(json.dumps(self.config))
        self.original = self.file.read_bytes()
        self.live = dict(idle=False, inIdleCycle=False, stayAwake=False, processes={})
        self.power = 'battery'
        self.locked = False
        for mock in [patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.base / 'config')}),
                     patch.object(idle.battery, 'STATE', self.base / 'state'),
                     patch.object(idle, 'source', side_effect=lambda: self.power),
                     patch.object(idle, 'runtime', side_effect=lambda: (self.live, self.locked))]:
            mock.start()
            self.addCleanup(mock.stop)

    def read(self):
        return json.loads(self.file.read_text())

    def prefs(self):
        return dict(version=1, separate=True, shared={'screensaver': 150, 'lock': 300},
                    battery={'screensaver': 120, 'lock': 300}, ac={'screensaver': 600, 'lock': 900})

    def apply(self, prefs=None, active=True):
        return idle.operate('apply', prefs or self.prefs(), idle.operate('status')['revision'], active, time.time() * 1000)

    def test_status_inherits_both_pairs_and_never_writes_shell(self):
        result = idle.operate('status')
        self.assertFalse(result['managed'])
        self.assertFalse(result['preferences']['separate'])
        self.assertEqual(result['preferences']['battery'], {'screensaver': 150, 'lock': 300})
        self.assertEqual(result['preferences']['ac'], result['preferences']['battery'])
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_apply_preserves_unrelated_settings_and_creates_backup(self):
        result = self.apply()
        self.assertEqual(result['active'], self.prefs()['battery'])
        saved = self.read()
        self.assertEqual(saved['bar'], self.config['bar'])
        self.assertTrue(saved['idle']['unrelated'])
        backups = list((self.base / 'state').glob('idle-shell-before-*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_ac_and_battery_switch_select_correct_pair(self):
        self.apply()
        self.power = 'ac'
        result = idle.operate('sync', active=True, active_at=time.time() * 1000)
        self.assertEqual(result['active'], self.prefs()['ac'])
        self.power = 'battery'
        self.assertEqual(idle.operate('sync', active=True, active_at=time.time() * 1000)['active'], self.prefs()['battery'])
        self.assertEqual(len(list((self.base / 'state').glob('idle-shell-before-*'))), 1)

    def test_sync_with_no_preferences_does_not_write(self):
        idle.operate('sync', active=True, active_at=time.time() * 1000)
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_inactive_monitor_defers_switch_until_activity(self):
        self.apply()
        self.power = 'ac'
        before = self.file.read_bytes()
        result = idle.operate('sync', active=False)
        self.assertTrue(result['pending'])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse(idle.operate('sync', active=True, active_at=time.time() * 1000)['pending'])

    def test_idle_cycle_and_locked_screen_never_change_deadlines(self):
        self.apply()
        self.power = 'ac'
        before = self.file.read_bytes()
        for flag in ('idle', 'inIdleCycle', 'screensaverStarted', 'locked', 'lockProcess'):
            with self.subTest(flag=flag):
                self.live = dict(idle=False, inIdleCycle=False, stayAwake=False, processes={})
                self.locked = flag == 'locked'
                if flag == 'lockProcess': self.live['processes']['lock'] = True
                elif flag != 'locked': self.live[flag] = True
                self.assertTrue(idle.operate('sync', active=True, active_at=time.time() * 1000)['pending'])
                self.assertEqual(self.file.read_bytes(), before)

    def test_apply_while_idle_saves_draft_but_preserves_active_pair(self):
        self.live['inIdleCycle'] = True
        result = self.apply()
        self.assertEqual(result['active'], {'screensaver': 150, 'lock': 300})
        self.assertTrue(result['pending'])
        self.assertEqual(result['preferences'], self.prefs())

    def test_shared_mode_uses_one_pair_for_either_source(self):
        prefs = self.prefs()
        prefs['separate'] = False
        self.apply(prefs)
        self.power = 'ac'
        self.assertEqual(idle.operate('sync', active=True, active_at=time.time() * 1000)['active'], prefs['shared'])

    def test_stay_awake_is_reported_without_changing_its_state(self):
        self.live['stayAwake'] = True
        self.assertTrue(self.apply()['stayAwake'])
        self.assertTrue(self.live['stayAwake'])

    def test_external_timeout_change_stops_automatic_overwrite(self):
        self.apply()
        config = self.read()
        config['idle']['lock'] = 60
        self.file.write_text(json.dumps(config))
        before = self.file.read_bytes()
        self.assertTrue(idle.operate('status')['externalChange'])
        with self.assertRaisesRegex(RuntimeError, 'outside Battery Care'):
            idle.operate('sync', active=True, active_at=time.time() * 1000)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse(self.apply()['externalChange'])

    def test_stale_draft_cannot_overwrite_another_idle_edit(self):
        revision = idle.operate('status')['revision']
        config = self.read()
        config['idle']['lock'] = 200
        self.file.write_text(json.dumps(config))
        with self.assertRaisesRegex(RuntimeError, 'changed elsewhere'):
            idle.operate('apply', self.prefs(), revision, True, time.time() * 1000)
        self.assertEqual(self.read()['idle']['lock'], 200)

    def test_other_widget_edit_is_preserved_when_applying_older_draft(self):
        revision = idle.operate('status')['revision']
        config = self.read()
        config['bar']['newSetting'] = 'keep'
        self.file.write_text(json.dumps(config))
        idle.operate('apply', self.prefs(), revision, True, time.time() * 1000)
        self.assertEqual(self.read()['bar']['newSetting'], 'keep')

    def test_invalid_custom_times_never_write(self):
        for value in (-1, 86401, True, '300', 1.5):
            with self.subTest(value=value):
                prefs = self.prefs()
                prefs['battery']['lock'] = value
                with self.assertRaises(ValueError): self.apply(prefs)
                self.assertEqual(self.file.read_bytes(), self.original)

    def test_custom_seconds_are_preserved(self):
        prefs = self.prefs()
        prefs['battery'] = dict(screensaver=91, lock=307)
        self.assertEqual(self.apply(prefs)['active'], prefs['battery'])

    def test_corrupt_shell_is_not_overwritten(self):
        self.file.write_text('broken')
        with self.assertRaises(ValueError): idle.operate('status')
        self.assertEqual(self.file.read_text(), 'broken')

    def test_symlink_config_is_rejected_without_touching_target(self):
        target = self.base / 'victim'
        target.write_bytes(self.original)
        self.file.unlink()
        self.file.symlink_to(target)
        with self.assertRaises(OSError): idle.operate('status')
        self.assertEqual(target.read_bytes(), self.original)

    def test_missing_idle_service_blocks_apply(self):
        with patch.object(idle, 'runtime', side_effect=RuntimeError('offline')):
            result = idle.operate('status')
            self.assertTrue(result['warning'])
            with self.assertRaisesRegex(RuntimeError, 'not changed'):
                idle.operate('apply', self.prefs(), result['revision'], True)
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_racing_config_writer_is_detected(self):
        with idle.battery.safe_directory(self.config_dir) as fd:
            raw, config = idle.read_config(fd)
            self.file.write_text('{"other":"write"}')
            with self.assertRaisesRegex(RuntimeError, 'changed while saving'):
                idle.write_config(fd, raw, config, backup=True)
        self.assertEqual(self.file.read_text(), '{"other":"write"}')

    def test_failed_backup_never_changes_shell(self):
        with patch.object(idle.battery, 'publish_file', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.apply()
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_charge_lock_does_not_block_idle_status(self):
        with idle.battery.locked():
            self.assertFalse(idle.operate('status')['managed'])

    def test_stale_or_missing_activity_evidence_defers_sync(self):
        self.apply()
        self.power = 'ac'
        before = self.file.read_bytes()
        for timestamp in (None, time.time() * 1000 - 2000, time.time() * 1000 + 2000):
            with self.subTest(timestamp=timestamp):
                self.assertTrue(idle.operate('sync', active=True, active_at=timestamp)['pending'])
                self.assertEqual(self.file.read_bytes(), before)

    def test_idle_cycle_started_during_request_blocks_switch(self):
        self.apply()
        self.power = 'ac'
        before = self.file.read_bytes()
        active = dict(idle=False, inIdleCycle=False, stayAwake=False)
        now_idle = dict(active, idle=True, inIdleCycle=True)
        with patch.object(idle, 'runtime', side_effect=[(active, False), (now_idle, False)]):
            self.assertTrue(idle.operate('sync', active=True, active_at=time.time() * 1000)['pending'])
        self.assertEqual(self.file.read_bytes(), before)

    def test_existing_immediate_timeout_is_preserved_across_apply(self):
        config = self.read()
        config['idle']['lock'] = 0
        self.file.write_text(json.dumps(config))
        status = idle.operate('status')
        prefs = status['preferences']
        prefs['separate'] = True
        prefs['battery']['screensaver'] = 60
        self.assertEqual(self.apply(prefs)['active']['lock'], 0)
        self.assertEqual(idle.operate('status')['preferences']['ac']['lock'], 0)


if __name__ == '__main__': unittest.main()
