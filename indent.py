import re
import sys
import time

from calendar import month_name
from datetime import datetime, timedelta

import pywikibot as pwb
import wikitextparser as wtp

from pywikibot import Page, Site, Timestamp
from pywikibot.tools import filter_unique
################################################################################

SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

MONTH_TO_INT = {month: i + 1 for i, month in enumerate(month_name[1:])}
SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser:[^\n]+\[\[[Uu]ser talk:[^\n]+([0-2]\d):([0-5]\d), ([1-3]?\d) '
    f'({"|".join(month for month in MONTH_TO_INT)}) '
    r'(2\d{3}) \(UTC\)'
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
        extra = y - x - 1
        for j in range(i + 1, n):
            z = indent_lvl(lines[j])
            if z < y:
                break
            # Do not change lines with '#' as an indent character.
            if '#' in indent_text(lines[j]):
                continue
            # lines[j] = lines[j][:z - extra] + lines[j][z:] # chop off end
            lines[j] = lines[j][extra:]     # chop off start
    return lines[1:]

def fix_indent_style(lines, keep_hashes=True):
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
    
        closest_min_lvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)
        min_text = indent_dict[closest_min_lvl] + line[closest_min_lvl:minlvl]
        if keep_hashes:
            new_prefix = ''
            for c1, c2 in zip(min_text, line[:minlvl]):
                if c2 == '#':
                    new_prefix += c2
                elif c1 != '#':
                    new_prefix += c1
                else:
                    new_prefix += c2
        else:
            new_prefix = min_text

        new_lines.append(new_prefix + line[minlvl:])
        indent_dict[lvl] = indent_text(new_lines[-1]) # record style
        previous_lvl = lvl
    return new_lines

################################################################################
def can_edit(page, n_sigs):
    title, text = page.title(), page.text

    if '<!--NO INDENTBOT' in text:
        return False

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
    current_time = Timestamp.fromISOformat(datetime.utcnow().isoformat()[:-7]+'Z')
    start_time = current_time - timedelta(minutes=delay)
    end_time = start_time - timedelta(minutes=chunk, seconds=1)

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

        if x['newlen'] - x['oldlen'] < 50:
            continue

        if x['timestamp'] <= start_ts:
            page = Page(SITE, x['title'])
            if can_edit(page, n_sigs=5):
                yield page
        not_latest.add(x['pageid'])

def make_fixes(text):
    wt = wtp.parse(text)

    bad_spans = []
    for x in wt.comments + wt.tables + wt.templates + wt.get_tags():
        i, j = x.span
        if i - 1 >= 0 and text[i - 1] == '\n':
            i -= 1
        if '\n' in text[i:j]:
            bad_spans.append((i, j))

    def not_in_bad_span(i):
        return not any(start<=i<end for start, end in bad_spans)

    # partition into lines
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c == '\n' and not_in_bad_span(i):
            lines.append(text[prev:i + 1])
            prev = i + 1
    lines.append(text[prev:]) # since Wikipedia strips newlines from the end
    # print(lines)

    # The order of these fixes is important.
    #Changing the order can change the effects.
    lines = fix_gaps(lines)
    lines = fix_extra_indents(lines)
    lines = fix_indent_style(lines)
    return ''.join(lines)

def fix_page(page):
    if type(page) == str:
        page = Page(SITE, page)
    new_text = make_fixes(page.text)
    if page.text != new_text:
        page.text = new_text
        try:
            page.save(summary='Adjusting indentation. Test edit. See the [[Wikipedia:Bots/Requests for approval/IndentBot|request for approval]].',
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
    print('main function')
    #main()

