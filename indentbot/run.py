import argparse
import logging
import sys

from pathlib import Path

import indent

################################################################################

def get_args():
    parser = argparse.ArgumentParser(
        description=('Bot that helps maintain consistent and correct '
            'indentation in discussion pages on Wikipedia.'))

    parser.add_argument('-c', '--chunk', type=int, default=2,
        help='minimum minutes between recent changes checkpoints (default: 2)')

    parser.add_argument('-d', '--delay', type=int, default=10,
        help='minimum minutes before fixing a page (default: 10)')

    parser.add_argument('-l', '--logfile',
        help='log filename (default: $HOME/logs/indentbot.log)')

    parser.add_argument('-t', '--total', type=int, default=float('inf'),
        help='maximum number of edits to make (default: inf)')
    
    parser.add_argument('-v', '--verbose', action='store_true',
        help='print the {{Diff2}} template for successful edits')
    return parser.parse_args()


def set_up_logging(logfile):
    """
    Set up log file at the given location, otherwise logs are stored in
    $HOME/logs/indentbot.log.
    The directory $HOME/logs will be created if it does not exist.
    """
    logger = logging.getLogger('indentbot_logger')
    if logfile is None:
        path = Path.home() / 'logs'
        path.mkdir(exist_ok = True)
        path = path / 'indentbot.log'
        logfile = str(path)

    file_handler = logging.FileHandler(filename=logfile)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)


def run():
    args = get_args()
    set_up_logging(logfile=args.logfile)
    indent.main(chunk=args.chunk, delay=args.delay,
        limit=args.total, quiet=not args.verbose)


if __name__ == '__main__':
    try:
        indent.set_status_page(True)
        run()
    except BaseException as e:
        indent.set_status_page(False)
        logging.getLogger('indentbot_logger').error(
            ('Ending run due to an exception of type '
             + type(e).__name__ + '.'))
        raise

