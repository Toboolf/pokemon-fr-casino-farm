"""Finding RetroArch's save file without making the user type a path."""

import os
import glob

ENV_VAR = "FRCOINS_SAVE"

# RetroArch writes <savefile_directory>/<corename>/<rom>.srm when
# sort_savefiles_enable is on, and <savefile_directory>/<rom>.srm when it is off.
SEARCH_GLOBS = (
    "~/Documents/RetroArch/saves/*/*.srm",
    "~/Documents/RetroArch/saves/*.srm",
    "~/Library/Application Support/RetroArch/saves/*/*.srm",
    "~/Library/Application Support/RetroArch/saves/*.srm",
)


class LocateError(Exception):
    """The save file could not be identified without help from the user."""


def candidates():
    found = []
    for pattern in SEARCH_GLOBS:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if path not in found:
                found.append(path)
    return found


def resolve(explicit=None):
    """Return the save path to operate on, or raise LocateError with advice."""
    if explicit:
        path = os.path.expanduser(explicit)
        if not os.path.isfile(path):
            raise LocateError("no such file: %s" % path)
        return path

    from_env = os.environ.get(ENV_VAR)
    if from_env:
        path = os.path.expanduser(from_env)
        if not os.path.isfile(path):
            raise LocateError("%s points at a missing file: %s" % (ENV_VAR, path))
        return path

    found = candidates()
    if not found:
        raise LocateError(
            "no .srm files found in the usual RetroArch save directories.\n"
            "Pass one explicitly with --save, or set %s." % ENV_VAR)
    if len(found) > 1:
        listing = "\n".join("  %s" % p for p in found)
        raise LocateError(
            "found %d save files; pick one with --save:\n%s" % (len(found), listing))
    return found[0]
