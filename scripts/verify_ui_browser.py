"""Compatibility entry point for the isolated pilot browser acceptance suite.

The old tab-based verifier has been replaced by the multipage workflow in
verify_pilot_browser.py, which owns its disposable database and local servers.
"""
from verify_pilot_browser import main


if __name__ == "__main__":
    main()
