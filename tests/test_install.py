import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


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
