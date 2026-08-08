"""Version metadata must stay aligned across package and FastAPI surfaces."""

from importlib.metadata import version

from app.main import app
from app.version import __version__


def test_application_and_package_version_share_one_source():
    assert __version__ == "0.4.0"
    assert app.version == __version__
    assert version("cortex-vol-analytics") == __version__
