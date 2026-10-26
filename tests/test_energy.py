"""Per-app energy counters from a simulated cgroup, /proc, and desktop-entry tree."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import energy as e  # noqa: E402

USER = 'user.slice/user-1000.slice/user@1000.service'


class EnergyFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cgroup = self.root / 'cgroup'
        self.proc = self.root / 'proc'
        self.apps = self.root / 'applications'
        self.apps.mkdir()
        for target, value in ((e, 'CGROUP'), (e, 'PROC')):
            patcher = patch.object(target, value, getattr(self, value.lower()))
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'Hyprland', 'LANG': 'de_AT.UTF-8'})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.temp.cleanup)
        self.desktop('chromium', 'Chromium', 'Exec=/usr/bin/chromium %U\nName[de]=Chromium-Browser\nStartupWMClass=chromium')
        self.desktop('kitty', 'kitty', 'Exec=kitty')
        self.desktop('kitty-open', 'kitty URL Launcher', 'Exec=kitty +open %U')
        self.desktop('Mail', 'Mail', 'Exec=omarchy-launch-webapp "https://mail.example.com/"')
        self.desktop('hyprland', 'Hyprland', 'Exec=Hyprland')

    def desktop(self, stem, name, extra):
        (self.apps / (stem + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=' + name + '\n' + extra + '\n')

    def unit(self, path, usage, pids=()):
        directory = self.cgroup / path
        directory.mkdir(parents=True)
        (directory / 'cpu.stat').write_text('usage_usec %d\nuser_usec 1\nsystem_usec 1\n' % usage)
        (directory / 'cgroup.procs').write_text(''.join('%d\n' % p for p in pids))
        return directory

    def process(self, pid, argv, cgroup, gpu=None):
        directory = self.proc / str(pid)
        (directory / 'fd').mkdir(parents=True)
        (directory / 'fdinfo').mkdir()
        (directory / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
        (directory / 'cgroup').write_text('0::/' + cgroup + '\n')
        for fd, info in enumerate(gpu or []):
            os.symlink('/dev/dri/renderD128', directory / 'fd' / str(fd))
            (directory / 'fdinfo' / str(fd)).write_text(info)

    def sample(self):
        return e.sample(e.DesktopIndex([self.apps]))


class EnergyTests(EnergyFixture):
    def test_unit_ids_strip_launcher_prefixes_and_random_suffixes(self):
        self.assertEqual(e.unit_id('app-Hyprland-gtk\\x2dlaunch-554264c0.scope'), 'gtk-launch')
        self.assertEqual(e.unit_id('app-org.chromium.Chromium-4195.scope'), 'org.chromium.Chromium')
        self.assertEqual(e.unit_id('kitty-281319-0.scope'), 'kitty')
        self.assertEqual(e.unit_id('app-com.onepassword.OnePassword@autostart.service'), 'com.onepassword.OnePassword')
        self.assertEqual(e.unit_id('pipewire.service'), 'pipewire')

    def test_groups_units_and_names_them_from_desktop_entries(self):
        self.unit(USER + '/app.slice/app-org.chromium.Chromium-4195.scope', 5_000_000)
        self.unit(USER + '/app.slice/app-graphical.slice/kitty-281319-0.scope', 2_000_000)
        self.unit(USER + '/app.slice/omarchy-thing.service', 7)
        self.unit(USER + '/session.slice/wayland-wm@hyprland.desktop.service', 3)
        self.unit('system.slice/upower.service', 9)
        self.unit('init.scope', 1)
        units = {u['id']: u for u in self.sample()['units']}
        chromium = units['/' + USER + '/app.slice/app-org.chromium.Chromium-4195.scope']
        self.assertEqual((chromium['name'], chromium['kind'], chromium['cpu']), ('Chromium-Browser', 'app', 5_000_000))
        self.assertEqual(units['/' + USER + '/app.slice/app-graphical.slice/kitty-281319-0.scope']['name'], 'kitty')
        self.assertEqual(units['/' + USER + '/app.slice/omarchy-thing.service']['kind'], 'service')
        self.assertEqual(units['/' + USER + '/session.slice/wayland-wm@hyprland.desktop.service']['name'], 'Hyprland')
        self.assertEqual(units['/system.slice/upower.service'], {
            'id': '/system.slice/upower.service', 'name': 'upower', 'kind': 'system',
            'cpu': 9, 'gpuNs': 0, 'gpuCycles': 0})
        self.assertEqual(units['/init.scope']['name'], 'systemd')
        self.assertNotIn('/' + USER, units)  # The user manager itself is a container.

    def test_launcher_scopes_are_named_after_their_program(self):
        launch = USER + '/app.slice/app-graphical.slice/app-Hyprland-gtk\\x2dlaunch-f396951b.scope'
        self.unit(launch, 1, [10, 11, 12])
        self.process(10, ['/usr/lib/chromium/chrome_crashpad_handler'], launch)
        self.process(11, ['/usr/lib/chromium/chromium', '--type=zygote'], launch)
        self.process(12, ['/usr/lib/chromium/chromium', '--type=renderer'], launch)
        webapp = USER + '/app.slice/app-graphical.slice/app-Hyprland-gtk\\x2dlaunch-aaaaaaaa.scope'
        self.unit(webapp, 1, [20])
        self.process(20, ['/usr/lib/chromium/chromium', '--app=https://mail.example.com'], webapp)
        script = USER + '/app.slice/app-graphical.slice/app-Hyprland-watch-bbbbbbbb.scope'
        self.unit(script, 1, [30])
        self.process(30, ['/bin/bash', '/usr/share/omarchy/bin/omarchy-watch'], script)
        unknown = USER + '/app.slice/app-graphical.slice/app-Hyprland-xdg\\x2dterminal\\x2dexec-cccccccc.scope'
        self.unit(unknown, 1, [40])
        self.process(40, ['/usr/bin/kitty', '--working-directory', '/home'], unknown)
        names = {u['id'].rsplit('/', 1)[1]: u['name'] for u in self.sample()['units']}
        self.assertEqual(names[launch.rsplit('/', 1)[1]], 'Chromium-Browser')
        self.assertEqual(names[webapp.rsplit('/', 1)[1]], 'Mail')
        self.assertEqual(names[script.rsplit('/', 1)[1]], 'omarchy-watch')
        self.assertEqual(names[unknown.rsplit('/', 1)[1]], 'kitty')

    def test_gpu_counters_count_each_drm_client_once(self):
        scope = USER + '/app.slice/app-org.chromium.Chromium-4195.scope'
        self.unit(scope, 1, [50, 51])
        xe = 'drm-driver:\txe\ndrm-pdev:\t0000:00:02.0\ndrm-client-id:\t%d\ndrm-cycles-rcs:\t%d\ndrm-total-cycles-rcs:\t%d\n'
        self.process(50, ['chromium'], scope + '/sub', [xe % (4, 100, 9000), xe % (4, 100, 9000)])
        self.process(51, ['chromium'], scope, [xe % (5, 30, 9100), 'drm-client-id:\t6\ndrm-engine-render:\t500 ns\n'])
        self.process(52, ['other'], 'outside.scope', [xe % (7, 999, 9999)])
        result = self.sample()
        unit = result['units'][0]
        self.assertEqual((unit['gpuCycles'], unit['gpuNs']), (130, 500))
        self.assertEqual(result['gpuClock'], 9100)

    def test_unreadable_processes_and_missing_counters_are_skipped(self):
        self.unit(USER + '/app.slice/broken.scope', 1)
        (self.cgroup / USER / 'app.slice/broken.scope/cpu.stat').unlink()
        self.process(60, ['x'], 'nowhere.scope')
        (self.proc / '60' / 'cmdline').unlink()
        self.assertEqual(self.sample()['units'], [])


class PowerModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(e.battery, 'STATE', Path(self.temp.name) / 'state')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_round_trip_is_private(self):
        self.assertIsNone(e.load_model())
        e.save_model('{"w": 25, "a": 10, "p": 200, "aa": 6, "ap": 90}')
        self.assertEqual(e.load_model(), {'w': 25.0, 'a': 10.0, 'p': 200.0, 'aa': 6.0, 'ap': 90.0})
        self.assertEqual(os.stat(e.battery.STATE / e.MODEL).st_mode & 0o777, 0o600)

    def test_invalid_models_are_rejected(self):
        for raw in ('[]', '{"w": 1}', '{"w": -1, "a": 0, "p": 0, "aa": 0, "ap": 0}',
                    '{"w": true, "a": 0, "p": 0, "aa": 0, "ap": 0}', '{"w": 1, "a": 0, "p": 0, "aa": 0, "ap": 0, "x": 1}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                e.save_model(raw)
        e.battery.STATE.mkdir(mode=0o700)
        (e.battery.STATE / e.MODEL).write_text('not json')
        self.assertIsNone(e.load_model(), 'a corrupt model never breaks sampling')

    def test_symlinked_model_is_ignored_and_never_followed(self):
        e.battery.STATE.mkdir(mode=0o700)
        target = Path(self.temp.name) / 'elsewhere'
        target.write_text('{"w": 25, "a": 10, "p": 200, "aa": 6, "ap": 90}')
        (e.battery.STATE / e.MODEL).symlink_to(target)
        self.assertIsNone(e.load_model())
        with self.assertRaises(OSError):
            e.save_model('{"w": 1, "a": 0, "p": 0, "aa": 0, "ap": 0}')
        self.assertIn('"w": 25', target.read_text())


if __name__ == '__main__':
    unittest.main()
