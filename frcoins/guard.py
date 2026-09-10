"""Environment checks that run before any save is modified."""

import subprocess

PROCESS_NAMES = ("RetroArch", "retroarch")


def retroarch_pids():
    """Return PIDs of running RetroArch processes, or [] if none / undetectable.

    RetroArch keeps SRAM in memory and flushes it on an autosave timer and again
    on close, so a save edited while content is loaded gets silently overwritten.
    An empty list is also returned when pgrep is unavailable -- the check is a
    safety net, not a dependency.
    """
    pids = []
    for name in PROCESS_NAMES:
        try:
            result = subprocess.run(["pgrep", "-x", name],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode == 0:
            for line in result.stdout.decode("ascii", "replace").split():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
    return sorted(set(pids))
