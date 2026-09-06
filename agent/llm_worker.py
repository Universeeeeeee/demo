"""Compatibility entry point for the renamed Agent worker."""

from agent.worker import *  # noqa: F401,F403
from agent.worker import main


if __name__ == "__main__":
    main()
