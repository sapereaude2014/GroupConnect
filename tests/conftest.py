"""Test-wide isolation: redirect $HOME to a temp dir so production code paths
(expanduser, ~/.config/groupconnect, ~/.local/run/groupconnect_ipc, etc.)
never touch the developer's real home directory.

This is the root-cause fix for the ~22 `gc_ws_test_*` directories that were
being left behind under ~/.local/run/groupconnect_ipc/ after every test run.
"""
import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_home(tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home")
    old = os.environ.get("HOME")
    os.environ["HOME"] = str(fake_home)
    # USERPROFILE matters on Windows; harmless to set on Linux.
    os.environ["USERPROFILE"] = str(fake_home)
    yield fake_home
    if old is not None:
        os.environ["HOME"] = old
        os.environ["USERPROFILE"] = old
    else:
        os.environ.pop("HOME", None)
        os.environ.pop("USERPROFILE", None)
