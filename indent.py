# Fix indentation in discussion pages on Wikipedia.
import logging
import re
import sys
import time

from calendar import month_name
from collections import OrderedDict
from datetime import datetime, timedelta

import wikitextparser as wtp

from pywikibot import Page, Site, Timestamp
################################################################################

SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')
LOGFILE = '/data/project/indentbot/logs/indentbot.logs'

MONTH_TO_INT = {month: i + 1 for i, month in enumerate(month_name[1:])}
SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser(?: talk)?:[^\n]+?'          # user page link
    r'([0-2]\d):([0-5]\d), '                  # hh:mm
    r'([1-3]?\d) '                            # day
    f'({"|".join(m for m in MONTH_TO_INT)}) ' # month name
    r'(2\d{3}) \(UTC\)'                       # yyyy
)


def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))

def indent_text(line):
    return re.match(r'[:*#]*', line)[0]

def indent_lvl(line):
    return len(indent_text(line))

def visual_lvl(line):
    # Hashes count for two lvls
    x = indent_text(line)
    return len(x) + x.count('#')


################################################################################
# Fix gaps between indented lines
def fix_gaps(lines, squish=True, single_only=False):
    """
    Remove gaps sandwiched indented lines.
    A gap is a sequence of blank lines.
    Set squish to False to KEEP blank lines preceding a line with indent lvl 1.
    Set single_only to False to remove single-line AND certain multi-line gaps.
    """
    lines = list(lines)
    i, n = 0, len(lines)
    while i < n:
        txt_i = indent_text(lines[i])
        lvl_i = len(txt_i)
        if lvl_i == 0:
            i += 1; continue

        j = next((k for k in range(i + 1, n) if not is_blank_line(lines[k])), n)
        if j == n:
            break

        txt_j = indent_text(lines[j])
        lvl_j = len(txt_j)
        if lvl_j >= 2 - squish:
            if j - i == 2:
                safe_to_remove = True
            elif single_only:
                safe_to_remove = False
            elif lvl_j>1:
                safe_to_remove = True
            else:
                hash_i = txt_i.replace('*', ':')
                hash_j = txt_j.replace('*', ':')
                safe_to_remove = hash_i.startswith(hash_j) or hash_j.startswith(hash_i)
            if safe_to_remove:
                for k in range(i + 1, j):
                    lines[k] = ''
        i = j
    return [x for x in lines if x]

################################################################################
def fix_extra_indents(lines, initial_pass = False):
    """
    Fix extra indentation.
    """
    lines = list(lines)
    lines.insert(0, '\n') # for handling first line edge case
    n = len(lines)
    for i in range(n - 1):
        l1, l2 = lines[i:i+2]
        x, y = indent_lvl(l1), indent_lvl(l2)
        diff = y - x
        if diff <= 1:
            continue

        # check that visually it is an overindentation
        if visual_lvl(l2) - visual_lvl(l1) <= 1:
            continue

        #if extra indent starts from '#' and ends with '*' or '#', then remove one less
        if x and lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
            diff -= 1

        for j in range(i + 1, n):
            l = lines[j]
            if indent_lvl(l) < y:
                break
            lines[j] = l[:x] + l[x+diff-1:] # cut l[x:y-1] from indentation
    return lines[1:] # don't return the extra line we inserted

################################################################################
# Fix mixed indentation types
def fix_indent_style(lines):
    """
    Do not mix indent styles. Each line's indentation style must match
    the most recently used indentation style.
    """
    new_lines = []
    prev_lvl = 0
    indent_dict = {0: ''}
    for line in lines:
        lvl = indent_lvl(line)
        minlvl = min(lvl, prev_lvl)

        # This is only necessary when using certain strategies to fix indentation lvls.
        # It's a generalization of the naive strategy, but has the same result for most pages.
        minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

        new_prefix = ''
        p1, p2 = 0, 0
        while p1 < minlvl and p2 < lvl:
            c1 = indent_dict[minlvl][p1]
            c2 = line[p2]
            if c1 == '#':
                if p2 <= lvl - 3 and line[p2:p2+2] == '::':
                    new_prefix += '#'
                    p2 += 1
                else:
                    new_prefix += c2
            elif c2 == '#':
                new_prefix += c2
            else:
                new_prefix += c1
            p1 += 1
            p2 += 1
        new_indent = new_prefix + line[p2:lvl]
        new_lines.append(new_indent + line[lvl:])
        indent_dict[len(new_indent)] = new_indent # record style
        prev_lvl = len(new_indent)
    return new_lines

################################################################################
# Apply the fixes to some text
def apply_fixes(text):
    lines = line_partition(text)

    new_lines = fix_gaps(lines)
    new_lines = fix_extra_indents(new_lines)
    new_lines = fix_indent_style(new_lines)

    while new_lines != lines:
        lines = new_lines
        new_lines = fix_gaps(new_lines)
        new_lines = fix_extra_indents(new_lines)
        new_lines = fix_indent_style(new_lines)
    return ''.join(new_lines)

def line_partition(text):
    """
    We break on all newlines except those which should not be split on because
    1) Editors may not want the list to break there, and logically continue the
       same list on the subsequent line (usually with colon indentation), or
    2) Mediawiki doesn't treat it as breaking a list.

    So, we break on all newlines EXCEPT
    1. newlines before tables
    2. newlines before templates
    3. newlines before tags
    -----------------------
    4. newlines immediately followed by a line consisting of spaces and comments
    5. newlines that are part of a segment of whitespace immediately preceding a category link
    """
    wt = wtp.parse(text)

    bad_spans = []
    for x in wt.tables + wt.templates + wt.get_tags():
        i, j = x.span
        if i - 1 >= 0 and text[i - 1] == '\n':
            i -= 1
        if '\n' in text[i:j]:
            bad_spans.append((i, j))

    for x in wt.comments:
        if '\n' in str(x):
            bad_spans.append(x.span)

    # newline followed by line consisting of spaces and comments only doesn't break lines
    for m in re.finditer(r'\n *<!--(.(?<!-->))*?-->(<!--(.(?<!-->))*?-->| )*(?=\n)', text, flags=re.S):
        bad_spans.append(m.span())

    # whitespace followed by a Category link doesn't break lines
    for m in re.finditer(r'\s+\[\[Category:', text, flags=re.I):
        if '\n' in m[0]:
            bad_spans.append(m.span())

    # now partition into lines
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c == '\n' and not any(start<=i<end for start, end in bad_spans):
            lines.append(text[prev:i + 1])
            prev = i + 1
    lines.append(text[prev:]) # since Wikipedia strips newlines from the end
    #print(lines)
    return lines

################################################################################
# Create continuous generator of pages to edit
def recent_changes(start, end):
    talk_spaces = [1, 3, 5, 7, 11, 13, 15, 101, 119, 711, 829]
    other_spaces = [4]
    spaces = talk_spaces + other_spaces

    seen = set()
    for change in SITE.recentchanges(start=start, end=end, changetype='edit',
            namespaces=spaces, minor=False, bot=False, redirect=False, reverse=True):
        title = change['title']

        # stop if IndentBot's talk page has been edited with appropriate edit summary
        if title == 'User talk:IndentBot' and 'STOP' in change.get('comment', ''):
            logger.error(f"Stopped by {change['user']} with edit to talk page. Revid {change['revid']}.")
            sys.exit(0)

        if title in seen:
            continue
        # Bytes should increase
        if change['newlen'] - change['oldlen'] < 42: # 42 is the answer to everything :)
            continue
        # check for signature with matching timestamp
        page = Page(SITE, title)
        text = page.text
        t = change['timestamp'] # e.g. 2021-10-19T02:46:45Z
        recent_sig_pat = (
            r'\[\[[Uu]ser(?: talk)?:[^\n]+?'   # user link
            fr'{t[11:13]}:{t[14:16]}, '        # hh:mm
            fr'{t[8:10].lstrip("0")} '         # day
            fr'{month_name[int(t[5:7])]} '     # month name
            fr'{t[:4]} \(UTC\)'                # yyyy
        )
        # check for at least a few signatures
        if not re.search(recent_sig_pat, text):
            continue
        for count, m in enumerate(re.finditer(SIGNATURE_PATTERN, text), start=1):
            if count >= 2:
                break
        else:
            continue

        seen.add(title)
        yield (title, t)

def continuous_pages_to_check(chunk=2, delay=10):
    """
    Check recent changes in intervals of chunk minutes (plus processing time).
    Give at least delay minutes of buffer time before editing.
    Should have chunk <= .2 * delay.
    """
    change_dict = OrderedDict() # right side is newer side
    delay, one_sec = timedelta(minutes=delay), timedelta(seconds=1)
    old_time = SITE.server_time() - timedelta(minutes=chunk)
    while True:
        current_time = SITE.server_time()
        # get new changes
        for title, ts in recent_changes(old_time+one_sec, current_time):
            change_dict[title] = ts
            change_dict.move_to_end(title)

        # yield pages that have waited long enough
        cutoff_ts = (current_time - delay).isoformat()
        item_view = change_dict.items()
        oldest = next(iter(item_view), None)
        while oldest is not None and oldest[1] < cutoff_ts:
            yield Page(SITE, oldest[0])
            change_dict.popitem(last=False)
            oldest = next(iter(item_view), None)

        old_time = current_time
        time.sleep(chunk * 60)

################################################################################
# Function to fix and save a page, and main function to run continuous program.
def fix_page(page):
    """
    Apply fixes to a page and save it.
    """
    if type(page) == str:
        page = Page(SITE, page)
    new_text = apply_fixes(page.text)
    if page.text != new_text:
        page.text = new_text
        try:
            page.save(summary='Adjusting indentation. Test edit. See the [[Wikipedia:Bots/Requests for approval/IndentBot|request for approval]] and report issues there.',
                minor=True, botflag=True, nocreate=True)
            return True
        except Exception as e:
            logger.exception('Error on save.')
    return False

def main(limit = None):

    if limit is None:
        limit = float('inf')
    count = 0
    for p in continuous_pages_to_check():
        count += fix_page(p)
        if count >= limit:
            break

if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    file_handler = logging.FileHandler(filename = "logs/indentbot.log")
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    print('main')

