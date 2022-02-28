import argparse
import logging
import time

from pathlib import Path

from pywikibot import Page
from pywikibot.exceptions import *

import pagequeue
import patterns as pat

from fixes import GapFix, StyleFix
from textfixer import TF

################################################################################

def get_args():
    parser = argparse.ArgumentParser(
        description=('Bot that helps maintain consistent and correct '
            'indentation in discussion pages on Wikipedia.'))

    parser.add_argument('chunk', type=int,
        help='minimum minutes between checkpoints')

    parser.add_argument('delay', type=int,
        help='minimum minutes of delay before fixing a page')

    parser.add_argument('-l', '--logfile',
        help='log filename (default: $HOME/logs/indentbot.log)')

    parser.add_argument('-t', '--total', type=int, default=float('inf'),
        help='maximum number of edits to make (default: inf)')

    parser.add_argument('--threshold', type=int, default=1,
        help='minimum total error score for an edit to be made (default: 1)')

    parser.add_argument('-v', '--verbose', action='store_true',
        help='print the {{Diff2}} template for successful edits')

    # Keyword options for the fixes.
    # gap
    parser.add_argument('--min_closing_lvl', type=int, default=1,
        help='minimum level of the closing line of a gap to be removed')
    parser.add_argument('--max_gap', type=int, default=1,
        help='maximum length of a gap to be removed')
    parser.add_argument('--allow_reset', action='store_true',
        help='allow gaps between a line with level>1 and a line with lvl=1')

    # style
    parser.add_argument('--hide_extra_bullets', type=int, default=0,
        help='determines how floating bullets inside an overindentation '
        'are treated. For more info, see the docstring for StyleFix.')
    parser.add_argument('--keep_last_asterisk', action='store_true',
        help='always keeps the rightmost asterisk')
    return parser.parse_args()


def set_up_logging(logfile):
    """
    Set up log file at the given location, otherwise logs are stored in
    $HOME/logs/indentbot.log.
    The directory $HOME/logs will be created if it does not exist.
    """
    logging.getLogger('pywiki').setLevel(logging.WARNING)
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


def fix_page(page, fixer, *, threshold):
    """
    Apply fixes to a page and save it if there was a change in the text.
    If save is successful, returns a string for Template:Diff2.
    Returns None (or raises an exception) otherwise.
    """
    title, title_link = page.title(), page.title(as_link=True)
    newtext, score = fixer.fix(page.text)
    if fixer.total_score >= threshold:
        page.text = newtext
        summary = ('Adjusted indent/list markup per [[MOS:INDENTMIX]], '
            + '[[MOS:INDENTGAP|INDENTGAP]], and [[MOS:LISTGAP|LISTGAP]]. '
            + '({} markup adjustments, {} blank lines removed) '.format(*score)
            + '[[Wikipedia:Bots/Requests for approval/IndentBot|Trial edit]].')
        try:
            page.save(summary=summary,
                      minor=False,
                      botflag=True,
                      nocreate=True,
                      quiet=True)
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
        else:
            return pat.diff_template(page)


def mainloop(args):
    """
    Keep in mind the parameters for each fix being used.
    In particular, for the GapFix class,
    a practical min_closing_lvl is either 1 or 2.
    Note that 1 is better for screen readers and isn't noticeably visually
    distinct from 2, but modifying even just the wikitext may
    annoy editors leaving gaps either to organize the wikitext or
    just out of preference. However, we shouldn't compromise
    on gaps where the closing line has indent level greater than 1.
    """
    chunk, delay, limit = args.chunk, args.delay, args.total
    threshold = args.threshold
    logger.info(('Starting run. '
        '(chunk={}, delay={}, limit={}, '
        'threshold={})').format(chunk, delay, limit, threshold))
    t1 = time.perf_counter()
    count = 0
    FIXER = TextFixer(
                StyleFix(
                    hide_extra_bullets=args.hide_extra_bullets,
                    keep_last_asterisk=args.keep_last_asterisk,
                    allow_reset=args.allow_reset),
                GapFix(
                    min_closing_lvl=args.min_closing_lvl,
                    max_gap=args.max_gap)
            )
    for p in pagequeue.continuous_page_gen(chunk, delay):
        diff = fix_page(p, FIXER, threshold=threshold)
        if diff:
            count += 1
            if args.verbose:
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
    pat.set_status_page('active')
    try:
        mainloop(chunk=args.chunk,
                 delay=args.delay,
                 limit=args.total,
                 threshold=args.threshold,
                 verbose=args.verbose)
    except BaseException as e:
        logger.error('Ending run due to {}.'.format(type(e).__name__))
        raise
    finally:
        pat.set_status_page('inactive')


if __name__ == '__main__':
    logger = logging.getLogger('indentbot_logger')
    run()

