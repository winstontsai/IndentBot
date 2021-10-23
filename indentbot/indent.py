# Fix indentation in discussion pages on Wikipedia.
import logging
import regex as re
import sys
import time

from calendar import month_name
from collections import OrderedDict
from datetime import datetime, timedelta

import pywikibot as pwb
import wikitextparser as wtp

from pywikibot import Page, Site, Timestamp
from pywikibot.exceptions import EditConflictError, OtherPageSaveError
from pywikibot.exceptions import PageSaveRelatedError

import patterns

from patterns import BAD_PREFIXES, COMMENT_RE, NAMESPACES, SANDBOXES
from patterns import in_subspan
################################################################################
logger = logging.getLogger('indentbot_logger')
SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

MONTH_TO_INT = {month: i + 1 for i, month in enumerate(month_name[1:])}
SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser(?: talk)?:[^\n]+?' +                  # user page link
    r'([0-2]\d):([0-5]\d), ' +                          # hh:mm
    r'([1-3]?\d) ' +                                    # day
    '(' + "|".join(m for m in MONTH_TO_INT) + ') ' +    # month name
    r'(2\d{3}) \(UTC\)'                                 # yyyy
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

def subtract_tstamps(x, y):
    return Timestamp.fromISOformat(x) - Timestamp.fromISOformat(y)

def is_talk_page(ns):
    return ns % 2 == 1

def has_linebreaking_newline(line):
    # Return True if line contains "real" line break besides at the end
    # Considers newlines preceding tables, templates, and tags.
    pat = '\n( |' + COMMENT_RE + r')*(\{[{|]|<[^!])'
    return bool(re.search(pat, line))

def diff_template(page, title=True):
    """
    Return string for Template:Diff2 for the given Page.
    """
    x = '{{Diff2|' + str(page.latest_revision_id)
    if title:
        x += '|' + page.title()
    return x + '}}'

################################################################################
# Fix gaps between indented lines
def fix_gaps(lines, squish=True, single_only=False):
    """
    Remove gaps sandwiched indented lines.
    A gap is a sequence of blank lines.
    Set squish to False to KEEP blank lines preceding a line with indent lvl 1.
    Set single_only to False to remove single-line AND certain multi-line gaps.

    lines argument may be altered.
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
            elif not single_only and lvl_j > 1:
                safe_to_remove = True
            if safe_to_remove:
                for k in range(i + 1, j):
                    lines[k] = ''
        i = j
    return [x for x in lines if x]

################################################################################
def fix_extra_indents(lines, initial_pass = False):
    """
    Fix extra indentation.

    lines argument may be altered.
    """
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

        #if starts from '#' and ends with '*' or '#', remove one less
        # if x and lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
        #     diff -= 1

        for j in range(i + 1, n):
            l = lines[j]
            if indent_lvl(l) < y:
                break
            lines[j] = l[:x] + l[x + diff - 1:] # cut l[x:y-1] from indentation
    return lines[1:] # don't return the extra line we inserted

################################################################################
# Fix mixed indentation types
def fix_indent_style(lines):
    """
    Do not mix indent styles. Each line's indentation style must match
    the most recently used indentation style.

    lines argument may be altered.
    """
    new_lines = []
    prev_lvl = 0
    indent_dict = {0: ''}
    for line in lines:
        lvl = indent_lvl(line)
        minlvl = min(lvl, prev_lvl)

        # necessary when using certain strategies to fix indentation lvls
        minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

        # ignore lines starting with table
        if re.match(fr':*( |{COMMENT_RE})*' + r'\{\|', line):
            new_indent = line[:lvl] # keep same indent
        else:
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

        # reset "memory" if list-breaking newline encountered
        if lvl == 0 or has_linebreaking_newline(new_lines[-1]):
            indent_dict = {0: ''}

    return new_lines

################################################################################
# Miscellaneous fixes, on text string

################################################################################
# Apply the fixes to some text
def line_partition(text):
    """
    We break on all newlines except those which should not be split on because
    1) Editors may not want the list to break there, and they logically
        continue the same list after whatever was introduced on that line
        (usually using colon indentation), or
    2) Mediawiki doesn't treat it as breaking a list.

    So, we break on all newlines EXCEPT
    1. newlines before tables
    2. newlines before templates
    3. newlines before tags
    -----------------------
    4. newlines immediately followed by a line consisting of
        spaces and comments only
    5. newlines that are part of a segment of whitespace
        immediately preceding a category link
    6. ?????
    """
    wt = wtp.parse(text)
    bad_spans = []

    for x in wt.tables + wt.templates + wt.get_tags():
        i, j = x.span
        m = re.search(fr'\n( |{COMMENT_RE})*\Z', text[:i])
        if m:
            i = m.start()
        if '\n' in text[i:j]:
            bad_spans.append((i, j))

    for x in wt.comments:
        if '\n' in str(x):
            bad_spans.append(x.span)

    # newline followed by line consisting of spaces and comments ONLY
    for m in re.finditer(fr'\n *{COMMENT_RE}( |{COMMENT_RE})*(?=\n)',
            text, flags=re.S):
        bad_spans.append(m.span())

    # whitespace followed by a Category link doesn't break lines
    for m in re.finditer(r'\s+\[\[Category:', text, flags=re.I):
        if '\n' in m[0]:
            bad_spans.append(m.span())

    # now partition into lines
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c == '\n' and not any(in_subspan(i, span) for span in bad_spans):
            lines.append(text[prev:i + 1])
            prev = i + 1
    lines.append(text[prev:]) # since Wikipedia strips newlines from the end
    #print(lines)
    return lines


def fix_text(text):
    lines = line_partition(text)

    new_lines = fix_gaps(lines)
    new_lines = fix_extra_indents(new_lines)
    new_lines = fix_indent_style(new_lines)

    while new_lines != lines:
        lines = list(new_lines)
        new_lines = fix_gaps(new_lines)
        new_lines = fix_extra_indents(new_lines)
        new_lines = fix_indent_style(new_lines)

    text = ''.join(new_lines)
    return text

def fix_text2(text):
    lines = line_partition(text)

    new_lines = fix_gaps(lines)
    new_lines = fix_extra_indents(new_lines)
    new_lines = fix_indent_style2(new_lines)

    while new_lines != lines:
        lines = list(new_lines)
        new_lines = fix_gaps(new_lines)
        new_lines = fix_extra_indents(new_lines)
        new_lines = fix_indent_style2(new_lines)

    text = ''.join(new_lines)
    return text

################################################################################
# Create continuous generator of pages to edit
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
    Only edit certain template pages. An "opt-in" for the template namespace.
    """
    p = ['Template:Did you know nominations/', ]
    return any(title.startswith(x) for x in p)

def should_not_edit(title):
    """
    Returns True if a page should not be edited based on its title.
    An "opt-out" based on titles.
    """
    if is_sandbox(title):
        return True

    if title.startswith('Template:') and not is_valid_template_page(title):
        return True

    if any(title.startswith(x) for x in BAD_PREFIXES):
        return True

    return False

def recent_changes(start, end, min_sigs=3):
    logger.info('Retrieving pages from {} to {}.'.format(start, end))

    # page cache for this function call
    pages = dict()

    for change in SITE.recentchanges(start=start, end=end, reverse=True,
            changetype='edit', namespaces=NAMESPACES,
            minor=False, bot=False, redirect=False):
        title, ns = change['title'], change['ns']
        revid = change['revid']
        user = change['user']
        comment = change.get('comment', '')
        ts = change['timestamp'] # e.g. 2021-10-19T02:46:45Z
        
        # stop if talk page edited with appropriate edit summary
        if title == 'User talk:IndentBot' and 'STOP' in comment:
            logger.error(("STOPPED by [[User:" + user + "]].\n"
                "Revid={revid}\nTimestamp={ts}\nComment={comment}"))
            sys.exit(0)

        if should_not_edit(title):
            continue

        # bytes should increase some amount, e.g. at least a signature size
        if change['newlen'] - change['oldlen'] < 42:
            continue

        # cache Page for this function call
        if title not in pages:
            pages[title] = Page(SITE, title)
        text = pages[title].text

        # check for a few signatures if not a talk page
        if not is_talk_page(ns):
            signatures = set()
            for m in re.finditer(SIGNATURE_PATTERN, text):
                signatures.add(m[0])
                if len(signatures) >= min_sigs:
                    break
            else:
                continue

        # always check for signature with matching timestamp
        recent_sig_pat = (
            r'\[\[[Uu]ser(?: talk)?:[^\n]+?'   # user link
            fr'{ts[11:13]}:{ts[14:16]}, '      # hh:mm
            fr'{ts[8:10].lstrip("0")} '        # day
            fr'{month_name[int(ts[5:7])]} '    # month name
            fr'{ts[:4]} \(UTC\)'               # yyyy
        )
        if not re.search(recent_sig_pat, text):
            continue

        yield (title, ts, pages[title])

def continuous_pages_to_check(chunk, delay):
    """
    Check recent changes in intervals of chunk minutes.
    Give at least delay minutes of buffer time before editing.
    Should have chunk <= delay / 5.
    """
    edits = OrderedDict()
    one_sec = timedelta(seconds=1)
    delay = timedelta(minutes=delay)
    old_time = SITE.server_time() - timedelta(minutes=chunk)

    while True:
        loop_start_time = time.perf_counter()
        current_time = SITE.server_time()
        # get new changes, append to edits dict
        for title, ts, page in recent_changes(old_time, current_time):
            edits[title] = (ts, page)
            edits.move_to_end(title)

        # yield pages that have waited long enough
        cutoff_ts = (current_time - delay).isoformat()
        view = edits.items()
        oldest = next(iter(view), None)
        # check if oldest is past the cutoff
        while oldest is not None and oldest[1][0] <= cutoff_ts:
            yield oldest[1][1]     # yield Page object
            del edits[oldest[0]]
            oldest = next(iter(view), None)

        old_time = current_time + one_sec
        time.sleep(chunk*60 - (time.perf_counter()-loop_start_time))

################################################################################
# Function to fix and save a page, and main function to run continuous program.
def fix_page(page):
    """
    Apply fixes to a page and save it if there was a change in the text.
    If no exception occurs on the save, return a string for Template:Diff2.
    Returns false if there is no change or there is an exception on save.
    """
    if type(page) == str:
        page = Page(SITE, page)
    title = page.title(as_link=True)
    # get latest version so that there is likely no edit conflict
    new_text = fix_text(page.get(force=True)) 
    if page.text != new_text:
        page.text = new_text
        try:
            page.save(summary=('Adjusted indentation. Trial edit. '
                'See [[Wikipedia:Bots/Requests for approval/IndentBot|BRFA]].'),
                nocreate=True, minor=False, quiet=True)
            return diff_template(page)
        except EditConflictError:
            logger.warning('Edit conflict for {}.'.format(title))
        except OtherPageSaveError as err:
            if err.reason.startswith('Editing restricted by {{bots}}'):
                logger.warning('Not allowed to edit {}.'.format(title))
            else:
                logger.exception('Other page save error for {}.'.format(title))
                sys.exit(0)
        except PageSaveRelatedError:
            logger.exception('Save related error for {}.'.format(title))
            sys.exit(0)
        except Exception:
            logger.exception('Unknown error when saving {}.'.format(title))
            sys.exit(0)

def main(chunk, delay, limit = float('inf'), quiet = True):
    logger.info('Starting run.')
    t1 = time.perf_counter()
    count = 0
    for p in continuous_pages_to_check(chunk=chunk, delay=delay):
        diff_template = fix_page(p)
        if diff_template:
            count += 1
            if not quiet:
                print(diff_template)
        elif not quiet:
            print('Failed to save {}.'.format(p.title(as_link=True)))

        if count >= limit:
            logger.info('Limit reached.')
            break

    t2 = time.perf_counter()
    logger.info('Ending run. Time elapsed = {} seconds.'.format(t2-t1))

if __name__ == "__main__":
    pass

