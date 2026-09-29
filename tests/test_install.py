import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backup_config


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / 'config'
        (self.config / 'omarchy').mkdir(parents=True)
        (self.config / 'omarchy/shell.json').write_text('{"original":true}\n')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.mock('omarchy', '''#!/bin/bash
case "$1 $2" in
  'plugin list') echo '[{"id":"dandiccf.battery-care"}]' ;;
  'plugin enable') exit "${TEST_ENABLE_EXIT:-0}" ;;
esac
''')
        self.mock('omarchy-shell', '#!/bin/bash\nexit 0\n')
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.config), PATH=str(self.bin) + ':' + os.environ['PATH'])
        self.link = self.config / 'omarchy/plugins/dandiccf.battery-care'

    def mock(self, name, content):
        target = self.bin / name
        target.write_text(content)
        target.chmod(0o755)

    def install(self):
        return subprocess.run([str(ROOT / 'install-local.sh')], env=self.env, capture_output=True, text=True, timeout=10)

    def test_install_links_source_and_backs_up_configuration(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.link.resolve(), ROOT)
        backups = list((self.config / 'omarchy').glob('*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '{"original":true}\n')
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_repeated_install_preserves_previous_backup(self):
        self.assertEqual(self.install().returncode, 0)
        original = next((self.config / 'omarchy').glob('*.bak'))
        (self.config / 'omarchy/shell.json').write_text('{"changed":true}\n')
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(len(list((self.config / 'omarchy').glob('*.bak'))), 2)
        self.assertEqual(original.read_text(), '{"original":true}\n')

    def test_backup_collisions_never_overwrite_or_follow_existing_paths(self):
        source = self.config / 'omarchy/shell.json'
        victim = self.base / 'victim'
        victim.write_text('keep')
        missing = self.base / 'missing'
        destination = source.with_name(source.name + '.battery-care.fixed.bak')
        for kind in ('file', 'symlink', 'dangling', 'hardlink', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                if kind == 'file': destination.write_text('previous backup')
                elif kind == 'symlink': destination.symlink_to(victim)
                elif kind == 'dangling': destination.symlink_to(missing)
                elif kind == 'hardlink': os.link(victim, destination)
                elif kind == 'directory': destination.mkdir()
                else: os.mkfifo(destination)
                with patch.object(backup_config.secrets, 'token_hex', return_value='fixed'):
                    with self.assertRaises(FileExistsError):
                        backup_config.backup_config(source)
                self.assertEqual(victim.read_text(), 'keep')
                self.assertFalse(missing.exists())
                self.assertFalse(list(source.parent.glob('.battery-care-*')))
                if kind == 'file': self.assertEqual(destination.read_text(), 'previous backup')
                if kind == 'directory': destination.rmdir()
                else: destination.unlink()

    def test_unsafe_config_backup_aborts_before_enable(self):
        self.mock('omarchy-shell', '#!/bin/bash\nexit 91\n')
        source = self.config / 'omarchy/shell.json'
        victim = self.base / 'victim'
        source.rename(victim)
        source.symlink_to(victim)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 91)
        self.assertIn('Configuration backup failed', result.stderr)
        self.assertEqual(victim.read_text(), '{"original":true}\n')
        self.assertFalse(self.link.is_symlink())

    def test_backup_refuses_symlinked_directory(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.config / 'omarchy', target_is_directory=True)
        with self.assertRaises(OSError):
            backup_config.backup_config(alias / 'shell.json')
        self.assertFalse(list((self.config / 'omarchy').glob('*.bak')))

    def test_missing_configuration_requires_no_backup(self):
        source = self.config / 'omarchy/shell.json'
        source.unlink()
        self.assertIsNone(backup_config.backup_config(source))
        self.assertIsNone(backup_config.backup_config(self.base / 'absent/shell.json'))

    def test_nonregular_config_aborts_before_enable(self):
        self.mock('omarchy-shell', '#!/bin/bash\nexit 91\n')
        # The verified reader refuses nonregular sources without blocking.
        source = self.config / 'omarchy/shell.json'
        source.unlink()
        os.mkfifo(source)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 91)
        self.assertIn('Configuration backup failed', result.stderr)
        self.assertFalse(self.link.is_symlink())

    def test_enable_failure_removes_only_new_link(self):
        self.env['TEST_ENABLE_EXIT'] = '1'
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.link.is_symlink())
        self.assertTrue(ROOT.is_dir())

    def test_existing_development_link_survives_enable_failure(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(ROOT)
        self.env['TEST_ENABLE_EXIT'] = '1'
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(self.link.resolve(), ROOT)

    def test_refuses_to_replace_unrelated_plugin(self):
        self.link.mkdir(parents=True)
        marker = self.link / 'user-data'
        marker.write_text('keep')
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(marker.read_text(), 'keep')

    def test_uninstall_refuses_unrelated_directory_before_actions(self):
        self.link.mkdir(parents=True)
        result = subprocess.run([str(ROOT / 'uninstall-local.sh')], env=self.env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.link.is_dir())
