# Fix indentation in discussion pages on Wikipedia.
import re
import sys
import time

from calendar import month_name
from datetime import datetime, timedelta

import wikitextparser as wtp

from pywikibot import Page, Site, Timestamp
################################################################################

SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

MONTH_TO_INT = {month: i + 1 for i, month in enumerate(month_name[1:])}
SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser(?: talk)?:[^\n]+?'          # user page link
    r'([0-2]\d):([0-5]\d), '                  # hh:mm
    r'([1-3]?\d) '                            # day
    f'({"|".join(m for m in MONTH_TO_INT)}) ' # month name
    r'(2\d{3}) \(UTC\)'                       # yyyy
)

def log_error(error):
    timestring = datetime.utcnow().isoformat()[-7]
    logfile = '/data/project/indentbot/logs/save_errors'
    with open(logfile, 'a') as f:
        print(f'{timestring} {x.page.pageid} [[{x.page.title()}]]: {x}',
            file=f, flush=True)

def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))

def indent_text(line):
    return re.match(r'[:*#]*', line)[0]

def indent_lvl(line):
    return len(indent_text(line))


################################################################################
# Fix gaps between indented lines
def fix_gaps(lines, squish=True, single_only=False):
    """
    Remove gaps sandwiched indented lines.
    A gap is a sequence of blank lines.
    Set squish to False to KEEP blank lines preceding a line with indent lvl 1.
    Set single_only to False to remove single-line AND certain multi-line gaps.
    """
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
            safe_to_remove = False
            if j - i == 2:
                safe_to_remove = True
            elif not single_only and (lvl_j>1 or txt_i.startswith(txt_j) or txt_j.startswith(txt_i)):
                safe_to_remove = True

            if safe_to_remove:
                for k in range(i + 1, j):
                    lines[k] = ''
        i = j

    return [x for x in lines if x]

################################################################################
def fix_extra_indents(lines):
    """
    Fix extra indentation.
    """
    lines.insert(0, '\n') # for handling first line edge case
    n = len(lines)
    for i in range(n - 1):
        x, y = indent_lvl(lines[i]), indent_lvl(lines[i+1])
        if y <= x + 1:
            continue
        #if extra indent is going from '#' to '#:*' or '#:#', then skip
        if lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
            continue
        diff = y - x
        for j in range(i + 1, n):
            l = lines[j]
            if indent_lvl(l) < y:
                break
            lines[j] = l[:x] + l[y-1:] # cut l[x:y-1] from indentation
    return lines[1:] # don't return the extra line we inserted


################################################################################
# Fix mixed indentation types
def fix_indent_style(lines):
    """
    Do not mix indent styles. Each line's indentation style must match
    the most recently used indentation style.
    """
    new_lines = []
    previous_lvl = 0
    indent_dict = {0: ''}
    for line in lines:
        lvl = indent_lvl(line)
        minlvl = min(lvl, previous_lvl)

        # This is only necessary when using certain strategies to fix indentation lvls.
        # It's a generalization of the naive strategy, but has the same result for most pages.
        closest_to_minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

        new_prefix = ''
        for c1, c2 in zip(indent_dict[closest_to_minlvl], line):
            if '#' in (c1, c2):
                new_prefix += c2
            else:
                new_prefix += c1
        new_lines.append(new_prefix + line[closest_to_minlvl:])

        indent_dict[lvl] = indent_text(new_lines[-1]) # record style
        previous_lvl = lvl
    return new_lines


################################################################################
# Apply the fixes to some text
def apply_fixes(text, rounds = 2):
    for i in range(rounds):
        lines = line_partition(text)
        lines = fix_gaps(lines)
        lines = fix_extra_indents(lines)
        lines = fix_indent_style(lines)
        text = ''.join(lines)
    return text

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
def can_edit(page, n_sigs):
    title, text = page.title(), page.text
    current_time = datetime.utcnow()
    recent = timedelta(days=1)
    has_recent_sig = False
    for count, m in enumerate(re.finditer(SIGNATURE_PATTERN, text), start=1):
        if not has_recent_sig:
            # year, month, day, hour, minute
            pieces = map(int, [m[5], MONTH_TO_INT[m[4]], m[3], m[1], m[2]])
            has_recent_sig = current_time - datetime(*pieces) < recent
        if count >= n_sigs and has_recent_sig:
            return True
    return False

def pages_to_check(chunk=10, delay=10):
    """
    Yields discussion pages edited between delay and delay+chunk minutes ago
    which are non-minor, non-bot, non-redirect,
    and have not had a non-minor, non-bot edit made in the last delay minutes.
    """
    current_time = SITE.server_time()
    start_time = current_time - timedelta(minutes=delay)
    end_time = start_time - timedelta(minutes=chunk, seconds=5)

    talk_spaces = [1, 3, 5, 7, 11, 13, 15, 101, 119, 711, 829]
    other_spaces = [4]
    spaces = talk_spaces + other_spaces

    avoid_tags = {'Undo', 'Manual revert'} # not currently used

    not_latest = set()
    start_ts = start_time.isoformat()
    for x in SITE.recentchanges(start=current_time, end=end_time, changetype='edit',
            namespaces=spaces, minor=False, bot=False, redirect=False,):

        # has been superseded by a newer non-minor, non-bot, 
        # potentially signature-adding edit
        if x['pageid'] in not_latest:
            continue

        # If a signature is added, the bytes should increase
        if x['newlen'] - x['oldlen'] < 42: # 42 is the answer to everything :)
            continue

        if x['timestamp'] <= start_ts:
            page = Page(SITE, x['title'])
            if can_edit(page, n_sigs=2):
                yield page
        not_latest.add(x['pageid'])

def fix_page(page):
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
            log_error(e)
    return False

def fix_page2(page):
    if type(page) == str:
        page = Page(SITE, page)
    new_text = apply_fixes2(page.text)
    if page.text != new_text:
        page.text = new_text
        try:
            page.save(summary='Adjusting indentation. Test edit. See the [[Wikipedia:Bots/Requests for approval/IndentBot|request for approval]] and report issues there.',
                minor=True, botflag=True, nocreate=True)
            return True
        except Exception as e:
            log_error(e)
    return False

def main(limit = None):
    if limit is None:
        limit = float('inf')

    count = 0
    for p in pages_to_check():
        count += fix_page(p)
        if count >= limit:
            break

if __name__ == "__main__":
    print(SIGNATURE_PATTERN)
    #main()

