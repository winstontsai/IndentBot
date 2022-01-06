import argparse
import logging
import sys
import time

from pathlib import Path

from pywikibot import Page
from pywikibot.exceptions import *

import pagequeue
import patterns as pat
from fixes import fix_gaps, fix_styles
from textfixer import TF

################################################################################

def get_args():
    parser = argparse.ArgumentParser(
        description=('Bot that helps maintain consistent and correct '
            'indentation in discussion pages on Wikipedia.'))

    parser.add_argument('-c', '--chunk', type=int,
        help='minimum minutes between recent changes checkpoints')

    parser.add_argument('-d', '--delay', type=int,
        help='minimum minutes before fixing a page')

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


def fix_page(page, fixer):
    """
    Apply fixes to a page and save it if there was a change in the text.
    If save is successful, returns a string for Template:Diff2.
    Returns None (or raises an exception) otherwise.
    """
    title, title_link = page.title(), page.title(as_link=True)
    fixer.fix(page.text)
    if fixer:
        page.text = fixer.text
        try:
            page.save(summary=pat.EDIT_SUMMARY + ' {}'.format(fixer.score),
                      minor=False,
                      botflag=True,
                      nocreate=True,
                      quiet=True)
            return pat.diff_template(page)
        except EditConflictError:
            logger.warning('Edit conflict for {}.'.format(title_link))
        except LockedPageError:
            logger.warning('{} is locked.'.format(title_link))
        except AbuseFilterDisallowedError:
            logger.warning(
                'Edit to {} prevented by abuse filter.'.format(title_link))
        except SpamblacklistError:
            logging.warning(
                'Edit to {} prevented by spam blacklist.'.format(title_link))
        except OtherPageSaveError as err:
            if err.reason.startswith('Editing restricted by {{bots}}'):
                logger.warning(
                    'Edit to {} prevented by {{{{bots}}}}.'.format(title_link))
            else:
                logger.exception(
                    'OtherPageSaveError for {}.'.format(title_link))
                raise
        except PageSaveRelatedError:
            logger.exception('PageSaveRelatedError for {}.'.format(title_link))
            raise
        except Exception:
            logger.exception('Error when saving {}.'.format(title_link))
            raise


def main(chunk, delay, limit, verbose):
    logger.info(('Starting run. '
        '(chunk={}, delay={}, limit={})').format(chunk, delay, limit))
    t1 = time.perf_counter()
    count = 0
    for p in pagequeue.continuous_page_generator(chunk=chunk, delay=delay):
        if pagequeue.STOPPED_BY:
            continue
        fixer = TF(fix_styles, fix_gaps)
        diff = fix_page(p, fixer)
        if diff:
            count += 1
            if verbose:
                print(diff)
        if count >= limit:
            logger.info('Limit ({}) reached.'.format(limit))
            break
    t2 = time.perf_counter()
    logger.info(('Ending run. Total edits={}. '
                 'Time elapsed={} seconds.').format(count, t2 - t1))


def run():
    args = get_args()
    set_up_logging(logfile=args.logfile)
    main(chunk=args.chunk,
         delay=args.delay,
         limit=args.total,
         verbose=args.verbose)


def set_status_page(status):
    page = Page(pagequeue.SITE, 'User:IndentBot/status')
    status = 'active' if status else 'inactive'
    page.text = status
    page.save(summary='Updating status: {}.'.format(status),
              minor=True,
              botflag=True,
              quiet=True,)


if __name__ == '__main__':
    logger = logging.getLogger('indentbot_logger')
    set_status_page(True)
    try:
        run()
    except BaseException as e:
        logger.error('Ending run due to {}.'.format(type(e).__name__))
        raise
    finally:
        set_status_page(False)

