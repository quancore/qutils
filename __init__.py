"""Initialise qutils as a package for poetry."""

import sentry_sdk

from launcher import bot
from utils.config import BOT_TOKEN, SENTRY_URL


def main():
    """Entry point for poetry script."""
    print(BOT_TOKEN)
    sentry_sdk.init(SENTRY_URL)
    bot.run(BOT_TOKEN)


if __name__ == '__main__':
    main()