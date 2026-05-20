"""
Legacy compatibility shim for the admin license manager GUI.

Use the secured implementation from gui.license_generator_gui.
"""

from gui.license_generator_gui import LicenseManagerGUI

__all__ = ["LicenseManagerGUI"]
