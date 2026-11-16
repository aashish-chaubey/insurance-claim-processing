"""Create all tables. Run once after starting Postgres."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401  (ensures models are registered on Base)
from app.db import Base, engine


def main():
    Base.metadata.create_all(engine)
    print("Tables created.")


if __name__ == "__main__":
    main()
