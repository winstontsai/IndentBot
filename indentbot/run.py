import argparse
import logging
import time
import sys

from pathlib import Path

import indent

def get_args():
    parser = argparse.ArgumentParser(description = 'Bot that helps maintain consistent and correct indentation in discussion pages on Wikipedia.')
    parser.add_argument('-c', '--chunk', type=int, default=2,
        help='minutes between recent changes checkpoints')
    parser.add_argument('-d', '--delay', type=int, default=10,
        help='buffer time in minutes before a page can be edited')

    parser.add_argument('-l', '--logfile', help='file to store logs in')
    parser.add_argument('-t', '--total', type=int,
        help='maximum number of edits to make')

    parser.add_argument('-v', '--verbose', action='store_true',
        help='print links to the diffs using {{Diff2}}')
    return parser.parse_args()

def set_up_logging(logfile = None):
    """
    Set up log file at given location, otherwise logs are stored in
    $HOME/logs/indentbot.log.
    The directory logs will be created if it does not exist.
    """
    logger = logging.getLogger('indentbot_logger')
    if logfile is None:
        path = Path.home() / 'logs'
        path.mkdir(exist_ok = True)
        path = path / 'indentbot.log'
        logfile = str(path)

    file_handler = logging.FileHandler(filename = logfile)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

if __name__ == '__main__':
    set_up_logging()
    args = get_args()
    print(args)
    #indent.main(limit=args.limit, quiet=not args.verbose)