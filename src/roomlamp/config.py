"""Runtime settings loaded from the process environment."""

from dotenv import load_dotenv


def load_env() -> None:
    """Load `.env` from the current working directory if it exists."""
    load_dotenv()
