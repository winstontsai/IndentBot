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
from pywikibot.pagegenerators import PreloadingGenerator

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
        self._len = 0
        self._entry_finder = {}
        self._REMOVED = '<removed-task>'
        self._counter = itertools.count(start=1)

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

    def add_from(self, it):
        for page in it:
            self.add_page(page)

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


def recent_changes_gen(start, end):
    """
    Yield recent changes between the timestamps start and end, inclusive,
    with the potential to be edited by IndentBot.
    """
    logger.info('Checking edits from {} to {}.'.format(start, end))
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=pat.NAMESPACES,
            minor=False, bot=False, redirect=False):
        if change['newlen'] - change['oldlen'] < 100:
            continue
        if title_filter(change['title']):
            continue
        yield change


def potential_page_gen(changes):
    """
    Converts a generator of recent changes to a generator of Page objects
    which have the potential to be edited by IndentBot.

    We use a PreloadingGenerator to reduce the number of API calls.
    """
    page_dict = {} # map titles to a set of timestamps
    for c in changes:
        page_dict.setdefault(c['title'], set()).add(c['timestamp'])
    for page in PreloadingGenerator(Page(SITE, title) for title in page_dict):
        title, text = page.title(), page.text
        if page.isTalkPage() or has_n_sigs(text, 5):
            for ts in page_dict[title]:
                if has_sig_with_timestamp(text, ts):
                    yield page
                    break


def continuous_page_gen(chunk, delay):
    """
    Check recent changes in intervals of chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Chunk should be a small fraction of delay.
    """
    sec, delay = timedelta(seconds=1), timedelta(minutes=delay)
    pq = PageQueue()
    tstart = time.perf_counter()
    old_time = SITE.server_time()
    cutoff = old_time - delay
    pq.add_from(
        potential_page_gen(
            recent_changes_gen(cutoff - timedelta(minutes=chunk), old_time)))
    yield from pq.pop_up_to(cutoff)
    last_load = old_time
    while True:
        time.sleep(max(0, 60*chunk - time.perf_counter() + tstart))
        tstart = time.perf_counter()
        current_time = SITE.server_time()
        cutoff = current_time - delay
        check_pause_or_resume(old_time + sec, current_time)
        if not PAUSED:
            if last_load < cutoff:
                rcgen = recent_changes_gen(last_load + sec, current_time)
                pq.add_from(potential_page_gen(rcgen))
                last_load = current_time
            yield from pq.pop_up_to(cutoff)
        old_time = current_time
        

################################################################################
# Helper functions
################################################################################
def sandbox(title):
    """
    Return True if the title looks like it belongs to a sandbox.
    """
    if title in pat.SANDBOXES:
        return True
    return bool(re.search(r'/sandbox(?: ?\d+)?(?:/|\Z)', title, flags=re.I))


def valid_template_page(title):
    """
    Only edit certain template pages.
    An "opt-in" for the template namespace.
    """
    return title.startswith('Template:Did you know nominations/')


def title_filter(title):
    """
    Returns True iff a page should NOT be edited based on its title only.
    """
    if sandbox(title):
        return True
    if title.startswith('Template:') and not valid_template_page(title):
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


def check_pause_or_resume(start, end):
    """
    Stop or resume the bot based on a talk page edits.
    Currently, the policy is that any autoconfirmed user or admin can stop
    the bot, while only admins can resume it.
    """
    global PAUSED
    page = Page(SITE, 'User talk:IndentBot')
    for rev in page.revisions(starttime=start, endtime=end, reverse=True):
        user = rev['user']
        groups = User(SITE, user).groups()
        cmt = rev.get('comment', '')
        revid = rev.revid
        ts = rev.timestamp.isoformat()
        if user in pat.MAINTAINERS or 'sysop' in groups:
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
                 "    Comment   = {}").format(user, revid, ts, cmt))
        elif cmt.endswith('RESUME') and PAUSED and can_resume:
            PAUSED = False
            pat.set_status_page('active')
            logger.warning(
                ("Resumed by {}.\n"
                 "    Revid     = {}\n"
                 "    Timestamp = {}\n"
                 "    Comment   = {}").format(user, revid, ts, cmt))


if __name__ == "__main__":
    pass

