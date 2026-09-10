"""Disk operations: timestamped backups and crash-safe writes."""

import os
import shutil
import tempfile
from datetime import datetime

BACKUP_SUFFIX = ".frcoins"


def backup_path(save_path, when=None):
    when = when or datetime.now()
    return "%s%s-%s.bak" % (save_path, BACKUP_SUFFIX, when.strftime("%Y%m%d-%H%M%S"))


def free_backup_path(save_path, when=None):
    """A backup path that does not exist yet.

    Timestamps are only second-resolution, so two runs in the same second would
    collide. An existing backup is never overwritten -- a counter is appended
    instead, because refusing to write at all would be a worse outcome than a
    slightly uglier filename.
    """
    target = backup_path(save_path, when)
    if not os.path.exists(target):
        return target
    stem = target[:-len(".bak")]
    for counter in range(1, 1000):
        candidate = "%s-%d.bak" % (stem, counter)
        if not os.path.exists(candidate):
            return candidate
    raise OSError("could not find an unused backup name for %s" % save_path)


def make_backup(save_path, when=None):
    """Copy the save aside before it is modified. Never overwrites a backup."""
    target = free_backup_path(save_path, when)
    shutil.copy2(save_path, target)
    return target


def write_atomic(path, data):
    """Replace `path` with `data` in one step.

    The new contents are written to a temporary file in the same directory and
    fsynced before being moved into place, so an interrupted run can never leave
    a half-written save behind.
    """
    directory = os.path.dirname(os.path.abspath(path))
    handle, temp = tempfile.mkstemp(dir=directory, prefix=".frcoins-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if os.path.exists(path):
            shutil.copystat(path, temp)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
