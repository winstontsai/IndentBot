"""
Fix indentation in discussion pages on Wikipedia.
This module is for tracking recent changes and applying the fixes.
"""
import heapq
import itertools
import logging
import sys
import time

from calendar import month_name, month_abbr
from collections import OrderedDict
from datetime import timedelta

import regex as re

from pywikibot import Page, Site, Timestamp, User
from pywikibot.exceptions import *

import patterns as pat

from textfixer import TF
from fixes import *

################################################################################

logger = logging.getLogger('indentbot_logger')
SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

# Certain users are allowed to stop and resume the bot.
# When stopped, the bot continues tracking edits, but does not edit any pages.
STOPPED_BY = None

################################################################################

class PageQueue:
    def __init__(self):
        self._pq = []
        self._entry_finder = {}
        self._REMOVED = '<removed-task>'
        self._counter = itertools.count()
        self._len = 0

    def remove_page(self, title):
        entry = self._entry_finder.pop(title)
        entry[-1] = self._REMOVED
        self._len -= 1

    def add_page(self, page):
        """Adds a page OR updates the priority of a page."""
        title = page.title()
        if title in self._entry_finder:
            self.remove_page(title)
        entry = [page.editTime(), next(self._counter), page]
        self._entry_finder[title] = entry
        heapq.heappush(self._pq, entry)
        self._len += 1

    def pop_page(self):
        while self._pq:
            priority, count, page = heapq.heappop(self._pq)
            if page is not self._REMOVED:
                del self._entry_finder[page.title()]
                self._len -= 1
                return page
        raise KeyError('pop from an empty PageQueue')

    def view_min(self):
        # Clear out removed items left at the front of the queue.
        # Also, update priority so that the true min is returned.
        while self._pq:
            priority, count, page = self._pq[0]
            if page is self._REMOVED:
                heapq.heappop(self._pq)
            else:
                try:
                    page.text = page.get(force=True)
                except IsRedirectPageError:
                    self.pop_page()
                    continue
                if page.editTime() > priority:
                    self.add_page(page)
                else:
                    return priority, page
        raise KeyError('empty PageQueue has no min')

    def __len__(self):
        return self._len


def continuous_page_generator(chunk, delay):
    """
    Check recent changes in intervals of (roughly) chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    """
    edits = OrderedDict()
    sec = timedelta(seconds=1)
    delay = timedelta(minutes=delay)
    old_time = SITE.server_time() - delay
    while True:
        current_time = SITE.server_time()
        # get new changes, append to edits dict
        for title, page in recent_changes(old_time + sec, current_time):
            edits[title] = page
            edits.move_to_end(title)
        # yield pages that have waited long enough
        cutoff = current_time - delay
        for title, page in list(edits.items()):
            if page.editTime() > cutoff:
                break
            # force update of text and edit time
            try:
                page.text = page.get(force=True)
            except IsRedirectPageError:
                del edits[title]
                continue
            new_time = page.editTime()
            # yield if old enough
            if new_time <= cutoff:
                yield page
                del edits[title]
        # re-sort edits by edit times
        edits = OrderedDict(
            sorted(edits.items(), key=lambda z: z[1].editTime())
        )
        old_time = current_time
        time.sleep(chunk*60)


def continuous_page_generator2(chunk, delay):
    """
    Check recent changes in intervals of (roughly) chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    """
    pq = PageQueue()
    sec = timedelta(seconds=1)
    delay = timedelta(minutes=delay)
    old_time = SITE.server_time() - delay
    while True:
        current_time = SITE.server_time()
        # get new changes
        for title, page in recent_changes(old_time + sec, current_time):
            pq.add_page(page)
        print(pq._pq)
        # yield pages that have waited long enough
        cutoff = current_time - delay
        while pq and pq.view_min()[0] <= cutoff:
            yield pq.pop_page()
        old_time = current_time
        time.sleep(chunk*60)


################################################################################
# Helper functions
################################################################################
def set_status_page(status):
    page = Page(SITE, 'User:IndentBot/status')
    status = 'active' if status else 'inactive'
    page.text = status
    page.save(summary='Updating status: {}.'.format(status),
              quiet=True,
              minor=True,
              botflag=True)


def is_talk_namespace(namespace_num):
    return namespace_num % 2 == 1


def diff_template(page, title=None):
    """
    Return a Template:Diff2 string for the given Page.
    """
    x = '{{Diff2|' + str(page.latest_revision_id)
    if title is None:
        x += '|' + page.title()
    elif type(title) == str:
        x += '|' + title
    return x + '}}'


def is_sandbox(title):
    """
    Return True if it's a sandbox.
    """
    if title in pat.SANDBOXES:
        return True
    return bool(re.search(r'/[sS]andbox(?: ?\d+)?(?:/|\Z)', title))


def is_valid_template_page(title):
    """
    Only edit certain template pages.
    An "opt-in" for the template namespace.
    """
    return pat.starts_with_prefix_in(title, pat.TEMPLATE_PREFIXES)


def title_filter(title):
    """
    Returns True if a page should not be edited based on its title.
    An "opt-out" based on titles.
    """
    if is_sandbox(title):
        return True
    if title.startswith('Template:') and not is_valid_template_page(title):
        return True
    if any(title.startswith(x) for x in pat.BAD_TITLE_PREFIXES):
        return True
    return False


def has_n_sigs(text, n):
    count = 0
    for m in re.finditer(pat.SIGNATURE_PATTERN, text):
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
    if title_filter(title):
        return False
    if title not in cache:
        cache[title] = Page(SITE, title)
    text = cache[title].text
    if not is_talk_namespace(change['ns']) and not has_n_sigs(text, 3):
        return False
    if not has_sig_with_timestamp(text, ts):
        return False
    return title, cache[title]


def check_stop_or_resume(c):
    # Stop or resume the bot based on a talk page edit.
    global STOPPED_BY
    title, user, cmt = c['title'], c['user'], c.get('comment', '')
    revid, ts = c['revid'], c['timestamp']
    if title != 'User talk:IndentBot':
        return
    grps = set(User(SITE, user).groups())
    allowed = {'extendedconfirmed', 'sysop'}

    if cmt.endswith('STOP') and not STOPPED_BY:
        if grps.isdisjoint(allowed) and user not in pat.MAINTAINERS:
            return
        STOPPED_BY = user
        set_status_page(False)
        logger.warning(
            ("STOPPED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))

    elif cmt.endswith('RESUME') and STOPPED_BY:
        if grps.isdisjoint({'sysop'}) and user not in pat.MAINTAINERS:
            return
        STOPPED_BY = None
        set_status_page(True)
        logger.warning(
            ("RESUMED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))


def recent_changes(start, end):
    if STOPPED_BY:
        logger.info('(IndentBot edits paused.) '
            'Checking edits from {} to {}.'.format(start, end))
    else:
        logger.info('Checking edits from {} to {}.'.format(start, end))
    # page cache for this checkpoint
    cache = dict()
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=pat.NAMESPACES,
            minor=False, bot=False, redirect=False):
        # check whether to pause or resume editing based on talk page
        check_stop_or_resume(change)
        result = should_edit(change, cache)
        if result:
            yield result


if __name__ == "__main__":
    pass

