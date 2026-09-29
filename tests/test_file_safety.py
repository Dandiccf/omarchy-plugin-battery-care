"""Marketplace regression cases: unsafe paths must never damage unrelated files."""
import contextlib
import io
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

from test_battery import BatteryFixture, b


class FileSafetyTests(BatteryFixture):
    def setUp(self):
        super().setUp()
        self.base = b.STATE
        self.state_dir = self.base / 'state'
        self.state_dir.mkdir(mode=0o700)
        state = patch.object(b, 'STATE', self.state_dir)
        state.start()
        self.addCleanup(state.stop)
        self.config = self.base / 'config'
        env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.config)})
        env.start()
        self.addCleanup(env.stop)
        self.units = b.unit_directory()
        self.units.mkdir(parents=True)
        self.victim = self.base / 'unrelated'
        self.victim.write_text('keep me\n')
        self.service = self.units / (b.UNIT + '.service')
        self.timer = self.units / (b.UNIT + '.timer')

    def assert_victim_untouched(self):
        self.assertEqual(self.victim.read_text(), 'keep me\n')

    def test_status_lock_symlink_does_not_truncate_target(self):
        (b.STATE / 'lock').symlink_to(self.victim)
        output = io.StringIO()
        with patch.object(b, 'UPower', return_value=self.api), patch('sys.argv', ['battery.py', 'status']), contextlib.redirect_stdout(output):
            self.assertEqual(b.main(), 1)
        self.assertIn('error', output.getvalue())
        self.assert_victim_untouched()

    def test_lock_dangling_symlink_does_not_create_target(self):
        missing = self.base / 'missing'
        (b.STATE / 'lock').symlink_to(missing)
        with self.assertRaises(OSError), b.locked():
            self.fail('Unsafe lock was accepted')
        self.assertFalse(missing.exists())

    def test_existing_lock_is_not_truncated(self):
        (b.STATE / 'lock').write_text('existing lock contents')
        with b.locked():
            self.assertEqual((b.STATE / 'lock').read_text(), 'existing lock contents')

    def test_lock_hardlink_is_rejected(self):
        os.link(self.victim, b.STATE / 'lock')
        with self.assertRaises(RuntimeError), b.locked():
            self.fail('Hardlinked lock was accepted')
        self.assert_victim_untouched()

    def test_fifo_lock_is_rejected_without_blocking(self):
        os.mkfifo(b.STATE / 'lock')
        with self.assertRaises(RuntimeError), b.locked():
            self.fail('FIFO lock was accepted')

    def test_foreign_owned_lock_is_rejected(self):
        (b.STATE / 'lock').touch()
        real_fstat = os.fstat

        def foreign_file(fd):
            info = real_fstat(fd)
            if stat.S_ISREG(info.st_mode):
                fields = list(info)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return info

        with patch.object(b.os, 'fstat', side_effect=foreign_file):
            with self.assertRaises(RuntimeError), b.locked():
                self.fail('Foreign lock was accepted')

    def test_state_directory_symlink_is_rejected(self):
        b.STATE.rmdir()
        b.STATE.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(OSError), b.locked():
            self.fail('Symlink directory was accepted')
        self.assertFalse((self.base / 'lock').exists())

    def test_symlinked_ancestor_is_rejected(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.base, target_is_directory=True)
        with patch.object(b, 'STATE', alias / 'state'):
            with self.assertRaises(OSError), b.locked():
                self.fail('Symlink ancestor was accepted')

    def test_existing_state_directory_becomes_private(self):
        b.STATE.chmod(0o755)
        with b.locked():
            self.assertEqual(stat.S_IMODE(b.STATE.stat().st_mode), 0o700)

    def test_shared_writable_directory_is_rejected(self):
        b.STATE.chmod(0o777)
        with self.assertRaises(RuntimeError), b.locked():
            self.fail('Shared writable directory was accepted')
        self.assertFalse((b.STATE / 'lock').exists())

    def test_state_symlink_is_neither_read_nor_replaced(self):
        target = b.STATE / 'state.json'
        target.symlink_to(self.victim)
        with self.assertRaises(OSError):
            b.read_state()
        with self.assertRaises(OSError):
            b.save_state(self.state)
        self.assertTrue(target.is_symlink())
        self.assert_victim_untouched()

    def test_unit_symlink_and_dangling_symlink_are_rejected(self):
        for target in (self.victim, self.base / 'missing'):
            with self.subTest(target=target):
                self.service.symlink_to(target)
                with patch.object(b, 'run') as run:
                    with self.assertRaises(OSError):
                        b.install_guard()
                    run.assert_not_called()
                self.assertTrue(self.service.is_symlink())
                self.assertFalse(self.timer.exists())
                self.service.unlink()
        self.assert_victim_untouched()
        self.assertFalse((self.base / 'missing').exists())

    def test_foreign_timer_blocks_all_unit_writes_and_systemctl(self):
        self.timer.write_text('unrelated timer')
        with patch.object(b, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'foreign or modified'):
                b.install_guard()
            run.assert_not_called()
        self.assertFalse(self.service.exists())
        self.assertEqual(self.timer.read_text(), 'unrelated timer')

    def test_hardlinked_unit_is_rejected(self):
        os.link(self.victim, self.service)
        with patch.object(b, 'run') as run:
            with self.assertRaises(RuntimeError):
                b.install_guard()
            run.assert_not_called()
        self.assert_victim_untouched()

    def test_fifo_unit_is_rejected_without_blocking(self):
        os.mkfifo(self.service)
        with patch.object(b, 'run') as run:
            with self.assertRaises(RuntimeError):
                b.install_guard()
            run.assert_not_called()

    def test_symlinked_unit_directory_is_rejected(self):
        self.units.rmdir()
        self.units.symlink_to(self.base, target_is_directory=True)
        with patch.object(b, 'run') as run:
            with self.assertRaises(OSError):
                b.install_guard()
            run.assert_not_called()
        self.assertFalse((self.base / self.service.name).exists())

    def test_unit_publication_cannot_clobber_concurrent_collision(self):
        real_link = os.link

        def race(src, dst, **kwargs):
            self.service.symlink_to(self.victim)
            return real_link(src, dst, **kwargs)

        with patch.object(b.os, 'link', side_effect=race), patch.object(b, 'run') as run:
            with self.assertRaises(FileExistsError):
                b.install_guard()
            run.assert_not_called()
        self.assert_victim_untouched()
        self.assertTrue(self.service.is_symlink())
        self.assertFalse(list(self.units.glob('.battery-care-*')))

    def test_install_is_idempotent_and_reuses_exact_legacy_units(self):
        for name, data in b.guard_files().items():
            (self.units / name).write_text(data)
        before = {p.name: p.stat().st_ino for p in self.units.iterdir()}
        with patch.object(b, 'run'):
            b.install_guard()
            b.install_guard()
        self.assertEqual(before, {p.name: p.stat().st_ino for p in self.units.iterdir()})

    def test_install_new_units_then_remove_only_owned_units(self):
        unrelated = self.units / 'another.service'
        unrelated.write_text('keep')
        with patch.object(b, 'run') as run:
            b.install_guard()
            for name, data in b.guard_files().items():
                self.assertEqual((self.units / name).read_text(), data)
                self.assertEqual((self.units / name).stat().st_nlink, 1)
            with b.checked_guard_directory() as fd:
                b.remove_guard(fd)
            self.assertIn(unittest.mock.call('systemctl', '--user', 'disable', '--now', b.UNIT + '.timer'), run.call_args_list)
        self.assertFalse(self.service.exists())
        self.assertFalse(self.timer.exists())
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_release_foreign_unit_keeps_pending_recovery_and_skips_hardware(self):
        self.full()
        self.api.calls.clear()
        self.timer.write_text('foreign')
        output = io.StringIO()
        with patch.object(b, 'UPower', return_value=self.api), patch('sys.argv', ['battery.py', 'release']), patch.object(b, 'run') as run, contextlib.redirect_stdout(output):
            self.assertEqual(b.main(), 1)
            run.assert_not_called()
        self.assertFalse(self.api.calls)
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'full')
        self.assertEqual(self.timer.read_text(), 'foreign')

    def test_remove_refuses_modified_owned_unit(self):
        with patch.object(b, 'run'):
            b.install_guard()
        self.service.write_text('changed by someone else')
        with patch.object(b, 'run') as run:
            with self.assertRaises(RuntimeError), b.checked_guard_directory():
                self.fail('Modified unit was accepted')
            run.assert_not_called()
        self.assertTrue(self.timer.exists())
        self.assertEqual(self.service.read_text(), 'changed by someone else')

    def test_remove_rechecks_after_systemctl_and_keeps_replaced_file(self):
        with patch.object(b, 'run'):
            b.install_guard()

        def replace_during_stop(*args):
            self.service.unlink()
            self.service.symlink_to(self.victim)

        with b.checked_guard_directory() as fd, patch.object(b, 'run', side_effect=replace_during_stop):
            with self.assertRaises(OSError):
                b.remove_guard(fd)
        self.assertTrue(self.service.is_symlink())
        self.assertTrue(self.timer.exists())
        self.assert_victim_untouched()

    def test_failed_unit_flush_prevents_publication_and_enable(self):
        with patch.object(b.os, 'fsync', side_effect=OSError('disk failure')), patch.object(b, 'run') as run:
            with self.assertRaises(OSError):
                b.install_guard()
            run.assert_not_called()
        self.assertFalse(self.service.exists())
        self.assertFalse(self.timer.exists())
        self.assertFalse(list(self.units.glob('.battery-care-*')))

    def test_directory_at_unit_path_is_rejected(self):
        self.service.mkdir()
        with patch.object(b, 'run') as run:
            with self.assertRaises(RuntimeError):
                b.install_guard()
            run.assert_not_called()
        self.assertTrue(self.service.is_dir())

    def test_release_symlink_unit_keeps_recovery_and_skips_actions(self):
        self.full()
        self.api.calls.clear()
        self.timer.symlink_to(self.victim)
        with patch.object(b, 'UPower', return_value=self.api), patch('sys.argv', ['battery.py', 'release']), patch.object(b, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.main(), 1)
            run.assert_not_called()
        self.assertFalse(self.api.calls)
        self.assertEqual(b.read_state()['batteries']['bat0']['mode'], 'full')
        self.assertTrue(self.timer.is_symlink())
        self.assert_victim_untouched()


if __name__ == '__main__':
    unittest.main()
