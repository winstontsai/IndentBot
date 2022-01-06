"""
This module is for tracking recent changes and generating Page objects
to be edited.
It uses an edit-time-based priority queue.
"""
import heapq
import itertools
import logging
import time

from calendar import month_name
from datetime import timedelta

import regex as re

from pywikibot import Page, Site, User

import patterns as pat

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
        self._counter = itertools.count(start=1)
        self._len = 0

    def __len__(self):
        return self._len

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
            prio, count, page = heapq.heappop(self._pq)
            if page is not self._REMOVED:
                del self._entry_finder[page.title()]
                self._len -= 1
                return page
        raise KeyError('pop from an empty PageQueue')

    def pop_up_to(self, priority):
        while self._pq:
            if self._pq[0][2] is self._REMOVED:
                heapq.heappop(self._pq)
            else:
                prio, page = self._pq[0][0], self._pq[0][2]
                if prio > priority:
                    return
                try:
                    page.text = page.get(force=True)
                except IsRedirectPageError:
                    self.pop_page()
                else:
                    if page.editTime() > priority:
                        self.add_page(page)
                    else:
                        yield self.pop_page()


def continuous_page_generator(chunk, delay):
    """
    Check recent changes in intervals of (roughly) chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    """
    pq = PageQueue()
    sec = timedelta(seconds=1)
    delay = timedelta(minutes=delay)
    old_time = SITE.server_time() - delay * 2
    while True:
        tstart = time.perf_counter()
        current_time = SITE.server_time()
        # get new changes
        for title, page in recent_changes(old_time + sec, current_time):
            pq.add_page(page)
        # yield pages that have waited long enough
        yield from pq.pop_up_to(current_time - delay)
        old_time = current_time
        time.sleep(max(0, chunk * 60 - time.perf_counter() + tstart))


def recent_changes(start, end):
    if STOPPED_BY:
        logger.info('(IndentBot edits paused.) '
            'Checking edits from {} to {}.'.format(start, end))
    else:
        logger.info('Checking edits from {} to {}.'.format(start, end))
    # page cache for this checkpoint
    cache = dict()
    changes = []
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=pat.NAMESPACES,
            minor=False, bot=False, redirect=False):
        # check whether to pause or resume editing based on talk page
        check_stop_or_resume(change)
        result = should_edit(change, cache)
        if result:
            changes.append(result)
    return changes


################################################################################
# Helper functions
################################################################################
def is_talk_namespace(namespace_num):
    return namespace_num % 2 == 1


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
    # Number of bytes should generally increase when someone is adding
    # a signed comment.
    if change['newlen'] - change['oldlen'] < 40:
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
    maintainer = user in pat.MAINTAINERS
    grps = set(User(SITE, user).groups())
    if cmt.endswith('STOP') and STOPPED_BY is None:
        if grps.isdisjoint({'autoconfirmed', 'sysop'}) and not maintainer:
            return
        STOPPED_BY = user
        set_status_page(False)
        logger.warning(
            ("STOPPED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))

    elif cmt.endswith('RESUME') and STOPPED_BY is not None:
        if 'sysop' not in grps and not maintainer:
            return
        STOPPED_BY = None
        set_status_page(True)
        logger.warning(
            ("RESUMED by {}.\n"
             "    Revid     = {}\n"
             "    Timestamp = {}\n"
             "    Comment   = {}".format(user, revid, ts, cmt)))


if __name__ == "__main__":
    pass

