"""
Fix indentation in discussion pages on Wikipedia.
This module is for tracking recent changes and applying the fixes.
"""
import logging
import sys
import time

from calendar import month_name
from collections import OrderedDict
from datetime import timedelta

import regex as re

from pywikibot import Page, Site, Timestamp, User
from pywikibot.exceptions import (EditConflictError, LockedPageError,
                                  OtherPageSaveError, PageSaveRelatedError)

from patterns import (BAD_TITLE_PREFIXES, MAINTAINERS, NAMESPACES, SANDBOXES,
                      SIGNATURE_PATTERN, TEMPLATE_PREFIXES)
from patterns import starts_with_prefix_in
from textfixer import TextFixer

################################################################################

logger = logging.getLogger('indentbot_logger')
SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

# Certain users are allowed to stop and resume the bot.
# When stopped, the bot continues tracking edits, but does not edit any pages.
STOPPED_BY = None

################################################################################
# Basic helper functions
################################################################################
def set_status_page(status):
    page = Page(SITE, 'User:IndentBot/status')
    status = 'active' if status else 'inactive'
    page.text = status
    page.save(summary='Updating status: {}.'.format(status), quiet=True)


def is_talk_namespace(namespace_num):
    return namespace_num % 2 == 1


def diff_template(page, title=True):
    """
    Return a Template:Diff2 string for the given Page.
    """
    x = '{{Diff2|' + str(page.latest_revision_id)
    if title:
        x += '|' + page.title()
    x += '}}'
    return x

################################################################################
# Functions to create continuous generator of pages to edit
################################################################################
def is_sandbox(title):
    """
    Return True if it's a sandbox.
    """
    if title in SANDBOXES:
        return True

    if re.search(r'/[sS]andbox(?: ?\d+)?(?:/|\Z)', title):
        return True
    return False


def is_valid_template_page(title):
    """
    Only edit certain template pages.
    An "opt-in" for the template namespace.
    """
    return starts_with_prefix_in(title, TEMPLATE_PREFIXES)


def should_not_edit_title(title):
    """
    Returns True if a page should not be edited based on its title.
    An "opt-out" based on titles.
    """
    if is_sandbox(title):
        return True
    if title.startswith('Template:') and not is_valid_template_page(title):
        return True
    if any(title.startswith(x) for x in BAD_TITLE_PREFIXES):
        return True
    return False


def has_n_sigs(text, n):
    count = 0
    for m in re.finditer(SIGNATURE_PATTERN, text):
        count += 1
        if count >= n:
            return True
    return False


def has_sig_with_timestamp(text, ts):
    recent_sig_pat = (
        r'\[\[[Uu]ser(?: talk)?:[^\n]+?'             # user link
        + r'{}:{}, '.format(ts[11:13], ts[14:16])    # hh:mm
        + ts[8:10].lstrip('0') + ' '                 # day
        + month_name[int(ts[5:7])] + ' '             # month name
        + ts[:4] + r' \(UTC\)'                       # yyyy
    )
    return re.search(recent_sig_pat, text)


def should_edit(change, cache):
    if change['newlen'] - change['oldlen'] < 42:
        return False
    title, ts = change['title'], change['timestamp']
    if should_not_edit_title(title):
        return False
    if title not in cache:
        cache[title] = Page(SITE, title)
    text = cache[title].text
    if not is_talk_namespace(change['ns']) and not has_n_sigs(text, 3):
        return False
    if not has_sig_with_timestamp(text, ts):
        return False
    return (title, ts, cache[title])


def check_stop_or_resume(c):
    # Stop or resume the bot based on a talk page edit.
    global STOPPED_BY
    title, user, cmt = c['title'], c['user'], c.get('comment', '')
    revid, ts = c['revid'], c['timestamp']
    if title != 'User talk:IndentBot':
        return
    grps = set(User(SITE, user).groups())
    if grps.isdisjoint({'extendedconfirmed', 'sysop'}) and user != 'IndentBot':
        return
    if cmt.endswith('STOP') and not STOPPED_BY:
        STOPPED_BY = user
        set_status_page(False)
        logger.warning(
            ("STOPPED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))
    elif cmt.endswith('RESUME') and STOPPED_BY:
        STOPPED_BY = None
        set_status_page(True)
        logger.warning(
            ("RESUMED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))


def recent_changes(start, end):
    logger.info('Checking edits from {} to {}.'.format(start, end))
    # page cache for this checkpoint
    cache = dict()
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=NAMESPACES,
            minor=False, bot=False, redirect=False):
        # check whether to pause or resume editing based on talk page
        check_stop_or_resume(change)
        result = should_edit(change, cache)
        if result:
            yield result


def continuous_page_generator(chunk, delay):
    """
    Check recent changes in intervals of (roughly) chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    Note that it's possible for a buffer not to be given if an edit
    is made between the checkpoint time and the actual save time.
    """
    edits = OrderedDict()
    sec = timedelta(seconds=1)
    delay = timedelta(minutes=delay)
    old_time = SITE.server_time() - delay
    while True:
        current_time = SITE.server_time()
        # get new changes, append to edits dict
        for title, ts, page in recent_changes(old_time + sec, current_time):
            edits[title] = (ts, page)
            edits.move_to_end(title)
        # yield pages that have waited long enough
        cutoff_ts = (current_time - delay).isoformat()
        view = edits.items()
        oldest = next(iter(view), None)
        # check if oldest timestamp at least as old as the cutoff timestamp
        while oldest and oldest[1][0] <= cutoff_ts:
            # yield the page and delete from edits
            yield oldest[1][1]
            del edits[oldest[0]]
            oldest = next(iter(view), None)
        old_time = current_time
        time.sleep(chunk*60)


################################################################################
# Function to fix and save a page.
################################################################################
def fix_page(page):
    """
    Apply fixes to a page and save it if there was a change in the text.
    If save is successful, returns a string for Template:Diff2.
    Returns None (or raises an exception) otherwise.
    """
    if type(page) == str:
        page = Page(SITE, page)
    title = page.title()
    title_link = page.title(as_link=True)
    # fix latest version so that there is no edit conflict
    tf = TextFixer(page.get(force=True))
    if sum(tf.score):
        page.text = tf.text
        try:
            page.save(summary=EDIT_SUMMARY,
                      minor=title.startswith('User talk:'),
                      nocreate=True,
                      quiet=True)
            return diff_template(page)
        except EditConflictError:
            logger.warning('Edit conflict for {}.'.format(title_link))
        except LockedPageError:
            logger.warning('{} is locked.'.format(title_link))
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

################################################################################
# Main function
################################################################################
def main(chunk, delay, limit=float('inf'), quiet=True):
    logger.info('Starting run.')
    t1 = time.perf_counter()
    count = 0
    for p in continuous_page_generator(chunk=chunk, delay=delay):
        if STOPPED_BY:
            continue
        diff_template = fix_page(p)
        if diff_template:
            count += 1
            if not quiet:
                print(diff_template)
        if count >= limit:
            logger.info('Limit reached.')
            break
    t2 = time.perf_counter()
    logger.info(('Ending run. Total edits = {}. '
                 'Time elapsed = {} seconds.').format(count, t2 - t1))


if __name__ == "__main__":
    pass

