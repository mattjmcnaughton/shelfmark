"""A keyboard-first personal reading desk"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("shelfmark")
except PackageNotFoundError:  # running from a Box release via PYTHONPATH=src
    __version__ = "0.1.0"
