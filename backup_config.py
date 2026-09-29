#!/usr/bin/python3
"""Create a private, no-clobber configuration backup for local installation."""
import contextlib
from pathlib import Path
import secrets
import sys

import battery


def backup_config(path):
    path = Path(path)
    with contextlib.ExitStack() as stack:
        try:
            directory_fd = stack.enter_context(battery.safe_directory(path.parent, create=False))
        except FileNotFoundError:
            return None
        raw = battery.read_owned(directory_fd, path.name)
        if raw is None:
            return None
        name = path.name + '.battery-care.' + secrets.token_hex(16) + '.bak'
        # Verified descriptor-based reads and no-clobber publication also refuse
        # collisions created between choosing the backup name and publishing it.
        battery.publish_file(directory_fd, name, raw)
        return path.parent / name


if __name__ == '__main__':
    try:
        result = backup_config(sys.argv[1])
        if result is not None:
            print('Configuration backup: ' + str(result))
    except (OSError, RuntimeError, UnicodeError) as error:
        print('Configuration backup failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
