from __future__ import annotations

import sys


def main() -> int:
    try:
        from sortdocs.gui.app import main as gui_main
    except ImportError as exc:  # pragma: no cover - depends on optional GUI extras
        message = (
            "sortdocs GUI requires PySide6. Install it with "
            "`pip install -e '.[gui]'` or `uv sync --extra gui`."
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from exc

    return gui_main()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
