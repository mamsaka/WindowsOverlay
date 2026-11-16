"""Run the Windows overlay application."""

try:
    from overlay.window import run
except ModuleNotFoundError as error:
    if error.name and error.name.startswith("PyQt6"):
        raise SystemExit(
            "Не найдены зависимости PyQt6. Выполните: "
            "python -m pip install -r requirements.txt"
        ) from error
    raise


if __name__ == "__main__":
    raise SystemExit(run())
