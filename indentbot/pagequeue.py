"""
This module is for tracking recent changes and generating Page objects
to be edited.
It uses a priority queue based on the most recent edit-time of a page.
"""
import heapq
import itertools
import logging
import time

from datetime import datetime, timedelta

import regex as re
import wikitextparser as wtp

from pywikibot import Page, Site, User
from pywikibot.exceptions import *
from pywikibot.pagegenerators import PreloadingGenerator

import patterns as pat

################################################################################
logger = logging.getLogger('indentbot_logger')
SITE = Site('en', 'wikipedia')
SITE.login(user='IndentBot')

# Certain users are allowed to stop and resume the bot.
PAUSED = False
################################################################################

class PageQueue:
    def __init__(self):
        self._pq = []
        self._len = 0
        self._entry_finder = {}
        self._REMOVED = '<removed-task>'
        self._counter = itertools.count(start=1)

    def clear(self):
        self._pq.clear()
        self._len = 0
        self._entry_finder.clear()
        self._counter = itertools.count(start=1)

    def __len__(self):
        return self._len

    def remove_page(self, title):
        entry = self._entry_finder.pop(title)
        entry[-1] = self._REMOVED
        self._len -= 1

    def add_page(self, page):
        """Adds a page OR updates the priority of a page."""
        title = page.title(with_ns=True)
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
                del self._entry_finder[page.title(with_ns=True)]
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
    logger.info(f'Retrieving edits from {start} to {end}.')
    # 0   (Main/Article)  Talk            1
    # 2   User            User talk       3
    # 4   Wikipedia       Wikipedia talk  5
    # 6   File            File talk       7
    # 8   MediaWiki       MediaWiki talk  9
    # 10  Template        Template talk   11
    # 12  Help            Help talk       13
    # 14  Category        Category talk   15
    # 100 Portal          Portal talk     101
    # 118 Draft           Draft talk      119
    # 710 TimedText       TimedText talk  711
    # 828 Module           Module talk    829
    TALK_SPACES = (1, 3, 5, 7, 11, 13, 15, 101, 119, 711, 829)
    OTHER_SPACES = (4, 10)
    NAMESPACES = TALK_SPACES + OTHER_SPACES
    for change in SITE.recentchanges(
            start=start, end=end, reverse=True,
            changetype='edit', namespaces=NAMESPACES,
            minor=False, bot=False, redirect=False):
        if change['newlen'] - change['oldlen'] < 100:
            continue
        if should_not_edit(change['title']):
            continue
        yield change


def potential_page_gen(changes):
    """
    Converts a generator of recent changes to a generator of Page objects
    which have the potential to be edited by IndentBot.

    We use a PreloadingGenerator to reduce the number of API calls.
    """
    pdict = {} # map titles to a set of timestamps
    for c in changes:
        pdict.setdefault(c['title'], set()).add(c['timestamp'])
    for page in PreloadingGenerator(Page(SITE, title) for title in pdict):
        title, text = page.title(with_ns=True), page.text
        # User/User talk pages must explicitly allow IndentBot
        if title.startswith('User') and not has_bot_allow_template(text):
            continue
        # In the Template namespace, only DYK nominations are allowed
        if title.startswith('Template:') and not valid_template_page(title):
            continue
        # Wikipedia namespace pages must have at least 5 signatures
        if title.startswith('Wikipedia:') and not has_n_sigs(5, text):
            continue
        # Must have a timestamp matching the edit time
        if not any(has_sig_with_timestamp(ts, text) for ts in pdict[title]):
            continue
        yield page


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
    rcgen = recent_changes_gen(cutoff - timedelta(minutes=chunk), old_time)
    pq.add_from(potential_page_gen(rcgen))
    last_load = old_time
    yield from pq.pop_up_to(cutoff)
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
        else:
            # Reset the queue whenever the bot gets paused.
            # Setting last_load to cutoff ensures
            # that there isn't a huge page load if the bot gets paused
            # for a while and then resumed.
            pq.clear()
            last_load = cutoff
        old_time = current_time


################################################################################
# Helper functions
################################################################################
def is_sandbox(title):
    """
    Return True if the title looks like it belongs to a sandbox.
    """
    SANDBOXES = (
        'Wikipedia:Sandbox',
        'Wikipedia talk:Sandbox',
        'Wikipedia:Articles for creation/AFC sandbox',
        'Wikipedia:AutoWikiBrowser/Sandbox',
        'User:Sandbox',
        'User talk:Sandbox',
        'User talk:Sandbox for user warnings',
        'User talk:192.0.2.16',
        'User talk:2001:DB8:10:0:0:0:0:1'
    )
    if title in SANDBOXES:
        return True
    return bool(re.search(r'/sandbox(?: ?\d+)?(?:/|\Z)', title, flags=re.I))


def valid_template_page(title):
    """
    Only edit certain template pages.
    An "opt-in" for the template namespace.
    """
    return title.startswith('Template:Did you know nominations/')


def should_not_edit(title):
    """
    Returns True iff a page should NOT be edited based only on its title.
    """
    if is_sandbox(title):
        return True
    if title.startswith('Template:') and not valid_template_page(title):
        return True
    BAD_TITLE_PREFIXES = frozenset([
        'Wikipedia:Arbitration/Requests/',
    ])
    if any(title.startswith(x) for x in BAD_TITLE_PREFIXES):
        return True
    return False


def has_n_sigs(n, text):
    """
    Returns True iff we find at least n user signatures in the text.
    """
    count = 0
    for m in re.finditer(pat.SIGNATURE_PATTERN, text):
        count += 1
        if count >= n:
            return True
    return False


def has_sig_with_timestamp(ts, text):
    """
    Returns an re.Match object corresponding to a user signature with the
    timestamp given by ts. Returns None if a match is not found.

    Example timestamp:
    2022-05-03T00:54:18Z
    Example signature:
    [[User:ASDF|FDSA]] ([[User talk:ASDF|talk]]) 01:24, 22 March 2022 (UTC)
    """
    dt = datetime.fromisoformat(ts.rstrip('Z'))
    mm = dt.strftime("%M")
    hh = dt.strftime("%H")
    day = dt.day
    mon = dt.strftime("%B")
    year = dt.strftime("%Y")
    p = fr'\[\[[Uu]ser(?: talk)?:[^\n]+?{hh}:{mm}, {day} {mon} {year} \(UTC\)'
    return re.search(p, text)


def has_bot_allow_template(text):
    """
    Returns True iff {{Bots}} (or one of its redirects) exists
    and IndentBot is named in the allow list.
    """
    names = ('Bots', 'Nobots', 'NOBOTS', 'Botsdeny', 'Bots deny')
    wt = wtp.parse(text)
    for template in wt.templates:
        if template.normal_name(capitalize=True) not in names:
            continue
        if allowed := template.get_arg('allow'):
            for x in allowed.value.split(','):
                if x.strip().lower() == 'indentbot':
                    return True
    return False


def check_pause_or_resume(start, end):
    """
    Stop or resume the bot based on a talk page edits.
    Currently, the policy is that any autoconfirmed user or admin can stop
    the bot, while only admins can resume it.
    """
    global PAUSED
    original_status = PAUSED
    page = Page(SITE, 'User talk:IndentBot')
    for rev in page.revisions(starttime=start, endtime=end, reverse=True):
        user   = rev['user']
        groups = User(SITE, user).groups()
        cmt    = rev.get('comment', '')
        revid  = rev.revid
        ts     = rev.timestamp.isoformat()
        if user in pat.MAINTAINERS or 'sysop' in groups:
            can_stop, can_resume = True, True
        elif 'autoconfirmed' in groups:
            can_stop, can_resume = True, False
        else:
            continue
        msg = ("{} by {}.\n"
               "    Revid     = {}\n"
               "    Timestamp = {}\n"
               "    Comment   = {}")
        if cmt.endswith('PAUSE') and not PAUSED and can_stop:
            PAUSED = True
            logger.warning(msg.format("Paused", user, revid, ts, cmt))
        elif cmt.endswith('RESUME') and PAUSED and can_resume:
            PAUSED = False
            logger.warning(msg.format("Resumed", user, revid, ts, cmt))
        if original_status != PAUSED:
            pat.set_status_page('paused' if PAUSED else 'active')


if __name__ == "__main__":
    pass

