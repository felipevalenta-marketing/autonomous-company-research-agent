"""Application entry point for the project foundation."""

from app.config.constants import PROJECT_NAME
from app.settings import load_settings


def main() -> None:
    """Run the minimal project entry point."""
    load_settings()
    print(PROJECT_NAME)
    print("Project foundation is configured correctly.")


if __name__ == "__main__":
    main()
