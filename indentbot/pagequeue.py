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
from pywikibot.exceptions import *

import patterns as pat

################################################################################

logger = logging.getLogger('indentbot_logger')
SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

# Certain users are allowed to stop and resume the bot.
# When stopped, the bot continues tracking edits, but does not edit any pages.
PAUSED = False

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
            prio, page = self._pq[0][0], self._pq[0][2]
            if prio > priority:
                break
            if page is self._REMOVED:
                heapq.heappop(self._pq)
            else:
                try:
                    page.text = page.get(force=True)
                except (IsRedirectPageError, NoPageError):
                    self.pop_page()
                else:
                    if page.editTime() > priority:
                        self.add_page(page)
                    else:
                        yield self.pop_page()


def continuous_page_generator(chunk, delay):
    """
    Check recent changes in intervals of chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    """
    pq = PageQueue()
    sec, delay = timedelta(seconds=1), timedelta(minutes=delay)
    old_time = SITE.server_time() - timedelta(minutes=chunk)
    old_cutoff = old_time - delay
    while True:
        tstart = time.perf_counter()
        current_time = SITE.server_time()
        cutoff = current_time - delay
        check_pause_or_resume(old_time + sec, current_time)
        if not PAUSED:
            # get new changes
            for page in recent_changes(old_cutoff + sec, cutoff):
                pq.add_page(page)
            # yield pages that have waited long enough
            yield from pq.pop_up_to(cutoff)
        old_time, old_cutoff = current_time, cutoff
        time.sleep(max(0, 60*chunk - time.perf_counter() + tstart))


def recent_changes(start, end):
    """
    Yield recent changes between the timestamps start and end, inclusive.
    """
    logger.info('Checking edits from {} to {}.'.format(start, end))
    # page cache for this checkpoint
    cache = dict()
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=pat.NAMESPACES,
            minor=False, bot=False, redirect=False):
        result = should_edit(change, cache)
        if result:
            yield result

################################################################################
# Helper functions
################################################################################
def is_talk_namespace(namespace_num):
    return namespace_num % 2 == 1


def is_sandbox(title):
    """
    Return True if the title looks like it belongs to a sandbox.
    """
    if title in pat.SANDBOXES:
        return True
    return bool(re.search(r'/[sS]andbox(?: ?\d+)?(?:/|\Z)', title))


def is_valid_template_page(title):
    """
    Only edit certain template pages.
    An "opt-in" for the template namespace.
    """
    return any(title.startswith(x) for x in pat.TEMPLATE_PREFIXES)


def title_filter(title):
    """
    Returns True iff a page should NOT be edited based on its title.
    """
    if is_sandbox(title):
        return True
    if title.startswith('Template:') and not is_valid_template_page(title):
        return True
    if any(title.startswith(x) for x in pat.BAD_TITLE_PREFIXES):
        return True
    return False


def has_n_sigs(text, n):
    """
    Returns True iff we find at least n user signatures in the text.
    """
    count = 0
    for m in re.finditer(pat.SIGNATURE_PATTERN, text):
        count += 1
        if count >= n:
            return True
    return False


def has_sig_with_timestamp(text, ts):
    """
    Returns an re.Match object corresponding to a user signature with the
    timestamp given by ts. Returns None if a match is not found.
    """
    recent_sig_pat = (
        r'\[\[[Uu]ser(?: talk)?:[^\n]+?'             # user link
        + r'{}:{}, '.format(ts[11:13], ts[14:16])    # hh:mm
        + ts[8:10].lstrip('0') + ' '                 # day
        + month_name[int(ts[5:7])] + ' '             # month name
        + ts[:4] + r' \(UTC\)'                       # yyyy
    )
    return re.search(recent_sig_pat, text)


def should_edit(change, cache):
    """
    Return False if we should not edit based on the change.
    Otherwise, return the appropriate Page object.
    """
    if change['newlen'] - change['oldlen'] < 100:
        return False
    title, ts = change['title'], change['timestamp']
    if title_filter(title):
        return False
    if title not in cache:
        cache[title] = Page(SITE, title)
    text = cache[title].text
    if not is_talk_namespace(change['ns']) and not has_n_sigs(text, 5):
        return False
    if not has_sig_with_timestamp(text, ts):
        return False
    return cache[title]


def check_pause_or_resume(start, end):
    """
    Stop or resume the bot based on a talk page edits.
    Currently, the policy is that any autoconfirmed user or admin can stop
    the bot, while only admins can resume it.
    """
    global PAUSED
    page = Page(SITE, 'User talk:IndentBot')
    for rev in page.revisions(starttime=start, endtime=end, reverse=True):
        cmt, user = rev.get('comment', ''), rev['user']
        revid, ts = rev.revid, rev.timestamp.isoformat()
        is_maintainer = user in pat.MAINTAINERS
        groups = User(SITE, user).groups()
        if is_maintainer or 'sysop' in groups:
            can_stop, can_resume = True, True
        elif 'autoconfirmed' in groups:
            can_stop, can_resume = True, False
        else:
            continue
        if cmt.endswith('PAUSE') and not PAUSED and can_stop:
            PAUSED = True
            pat.set_status_page('paused')
            logger.warning(
                ("Paused by {}.\n"
                 "    Revid     = {}\n"
                 "    Timestamp = {}\n"
                 "    Comment   = {}".format(user, revid, ts, cmt)))
        elif cmt.endswith('RESUME') and PAUSED and can_resume:
            PAUSED = False
            pat.set_status_page('active')
            logger.warning(
                ("Resumed by {}.\n"
                 "    Revid     = {}\n"
                 "    Timestamp = {}\n"
                 "    Comment   = {}".format(user, revid, ts, cmt)))


if __name__ == "__main__":
    pass

