from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from sortdocs.gui.main_window import SortdocsMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("sortdocs")
    app.setOrganizationName("sortdocs")
    window = SortdocsMainWindow()
    window.show()
    return app.exec()
