# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Environment discovery: what this machine can do."""

from .discover import (build, discover, find_app, find_program, hardware, list_apps, machine_for_selection,
                       os_info, python_packages, summary)
from .hints import headless_mode, install_hint

__all__ = ["build", "discover", "find_app", "find_program", "hardware", "list_apps", "machine_for_selection",
           "os_info", "python_packages", "summary", "headless_mode", "install_hint"]
