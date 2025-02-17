from __future__ import annotations

import asyncio
import logging
import sys

from twitch import logger
from twitch import setup
from twitch._exceptions import CONNECTION_EXCEPTION
from twitch._exceptions import EXCEPTIONS

# TODO)):
# - [X] ~Read https://dev.twitch.tv/docs/api/reference/#get-games~
# - [ ] Replace `argsparse` with `click`
# Config:
# - [X] Move config yaml file into $XDG_CONFIG_HOME


def main() -> int:
    args = setup.args()
    if args.help:
        setup.help()
        return 0

    logger.verbose(args.verbose)
    log = logging.getLogger(__name__)
    if args.verbose:
        log.debug('arguments: %s', vars(args))

    menu = setup.menu(args)
    try:
        run = asyncio.run
        twitch = run(setup.app(menu, args))
        twitch = setup.keybinds(twitch)

        if args.test:
            return run(setup.test(t=twitch))
        if args.channel:
            return run(twitch.show_by_query())
        if args.games:
            return run(twitch.show_by_game())
        return run(twitch.show_all_streams())
    except (*CONNECTION_EXCEPTION, *EXCEPTIONS) as err:
        menu.keybind.unregister_all()
        menu.select(items=[f'{err!r}'], markup=False, prompt='PyTwitchErr>')
        log.error(err)
    except KeyboardInterrupt:
        log.info('terminated by user')
    return 1


if __name__ == '__main__':
    sys.exit(main())
