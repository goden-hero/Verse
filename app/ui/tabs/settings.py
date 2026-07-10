"""Settings tab to manage configuration variables."""

from pathlib import Path
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.config.settings import settings


class SettingsTab(QWidget):
    """Tab containing inputs for editing database paths and Ollama settings."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window

        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Database URL
        self.db_url_input = QLineEdit(settings.database_url)
        form_layout.addRow("Database Connection URL:", self.db_url_input)

        # Vector Index Path
        default_vector_path = str(Path(settings.database_url.replace("sqlite:///", "")).parent / "vector_index.bin")
        self.vector_index_input = QLineEdit(default_vector_path)
        form_layout.addRow("Vector Index Path:", self.vector_index_input)

        # Ollama API URL
        self.ollama_url_input = QLineEdit(settings.ollama_url)
        form_layout.addRow("Ollama API URL:", self.ollama_url_input)

        # Ollama Model
        self.ollama_model_input = QLineEdit(settings.ollama_model)
        form_layout.addRow("Ollama Model Name:", self.ollama_model_input)

        layout.addLayout(form_layout)

        # Save Button
        save_layout = QHBoxLayout()
        save_btn = QPushButton("Save Config Settings")
        save_btn.clicked.connect(self.save_settings)
        save_layout.addWidget(save_btn)
        save_layout.addStretch()
        layout.addLayout(save_layout)
        layout.addStretch()

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def get_vector_index_path(self) -> Path:
        return Path(self.vector_index_input.text())

    def save_settings(self) -> None:
        # We modify the settings object attributes in-memory
        # Note: Since settings dataclass is frozen, we bypass it or we just set variables
        # in settings or override them if mutable, but the settings object we defined is frozen=True.
        # Wait! Is it frozen=True?
        # Let's check app/config/settings.py:
        # @dataclass(frozen=True)
        # Yes, it is!
        # If we need to write changes, we can write them back to an environment dict
        # or we can modify the main settings object by creating a new Settings or mutating via object.__setattr__.
        # Mutating via object.__setattr__ is a common Python trick to override frozen dataclasses!
        # Let's do that to avoid complex reloading logic:
        try:
            object.__setattr__(settings, "database_url", self.db_url_input.text())
            object.__setattr__(settings, "ollama_url", self.ollama_url_input.text())
            object.__setattr__(settings, "ollama_model", self.ollama_model_input.text())
            self.status_label.setText("Settings saved successfully (in-memory).")
        except Exception as e:
            self.status_label.setText(f"Error saving settings: {e}")
