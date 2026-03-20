from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from sortdocs.onboarding import (
    OPENAI_API_BILLING_URL,
    OPENAI_API_KEY_ENV,
    OPENAI_API_KEYS_URL,
    OPENAI_API_QUICKSTART_URL,
    get_onboarding_paths,
    save_api_key,
)


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set OpenAI API Key")
        self.setModal(True)
        self.resize(560, 220)

        layout = QVBoxLayout(self)

        info_label = QLabel(
            "<b>sortdocs</b> needs an OpenAI Platform API key to classify files.<br><br>"
            f"Create a key: <a href='{OPENAI_API_KEYS_URL}'>{OPENAI_API_KEYS_URL}</a><br>"
            f"Setup guide: <a href='{OPENAI_API_QUICKSTART_URL}'>{OPENAI_API_QUICKSTART_URL}</a><br>"
            "Billing note: ChatGPT and API usage are billed separately.<br>"
            f"Learn more: <a href='{OPENAI_API_BILLING_URL}'>{OPENAI_API_BILLING_URL}</a>"
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("Paste your OpenAI API key")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setClearButtonEnabled(True)
        self.key_input.setFocus(Qt.OtherFocusReason)
        layout.addWidget(self.key_input)

        paths = get_onboarding_paths()
        self.save_checkbox = QCheckBox(f"Save for future runs in {paths.env_path}")
        self.save_checkbox.setChecked(True)
        layout.addWidget(self.save_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._accept_and_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_and_save(self) -> None:
        api_key = self.key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing API Key", "Please paste a non-empty OpenAI API key.")
            return

        os.environ[OPENAI_API_KEY_ENV] = api_key
        if self.save_checkbox.isChecked():
            try:
                save_api_key(paths=get_onboarding_paths(), api_key=api_key)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "Could Not Save API Key",
                    f"The key will be used for this run, but it could not be saved.\n\n{exc}",
                )

        self.accept()
