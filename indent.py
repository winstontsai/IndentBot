import re
import sys
import time

from datetime import timedelta

import pywikibot as pwb
import wikitextparser as wtp

from pywikibot import Page, Site, Timestamp
from pywikibot.tools import filter_unique
################################################################################

SITE = Site('en','wikipedia')
SITE.login(user='IndentBot')

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
def has_n_signatures(text, n = 5):
    pat = (
        r'\[\[User:[^\n]+\[\[User talk:[^\n]+[0-2]\d:[0-5]\d, [1-3]?\d '
        r'(January|February|March|April|May|June|July|August|September|October|November|December) '
        r'2\d{3} \(UTC\)'
    )
    return any(i >= n for i, j in enumerate(re.finditer(pat, text), start=1))

def get_pages_to_check(chunk=10, delay=10):
    """
    Yields discussion pages edited between delay and delay+chunk minutes ago
    which are non-minor, non-bot, non-redirect,
    and have not had a non-minor, non-bot edit made in the last delay minutes.
    """
    server_time = SITE.server_time()
    start = server_time - timedelta(minutes=delay)
    end = start - timedelta(minutes=chunk)

    # 0   (Main/Article)  Talk              1
    # 2   User            User talk         3
    # 4   Wikipedia       Wikipedia talk    5
    # 6   File            File talk         7
    # 8   MediaWiki       MediaWiki talk    9
    # 10  Template        Template talk     11
    # 12  Help            Help talk         13
    # 14  Category        Category talk     15
    talk_spaces = [1, 3, 5, 7, 11, 13, 15, 101, 119, 711, 829]
    other_spaces = [4]

    not_latest, changes, start = set(), [], start.isoformat()
    for x in SITE.recentchanges(start=server_time, end=end, changetype='edit',
            namespaces=talk_spaces + other_spaces, 
            minor=False, bot=False, redirect=False,):
        if x['timestamp'] <= start and x['pageid'] not in not_latest:
            changes.append(x)  
        not_latest.add(x['pageid'])
    print(len(changes))

    for change in changes:
        title = change['title']
        ns = change['ns']

        if re.search(r'/([sS]andbox|[aA]rchive|[lL]og)\b', title):
            continue

        page = Page(SITE, title)
        if not (ns % 2 or has_n_signatures(page.text, 5)):
            continue

        yield page

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
    #print(lines)

    # The order of these fixes is important.
    #Changing the order can change the effects.
    lines = fix_gaps(lines)
    lines = fix_extra_indents(lines)
    lines = fix_indent_style(lines)
    
    return ''.join(lines)

def fix_page(page):
    if type(page) == str:
        page = Page(SITE, page)
    original_text = page.text
    page.text = make_fixes(original_text)
    if page.text != original_text:
        try:
            page.save(summary='Adjusting indentation. Test.', minor=True, nocreate=True)
            return True
        except pwb.exceptions.EditConflictError:
            return False
    return False

def main(limit = None):
    if limit is None:
        limit = float('inf')
    count = 0
    for title in get_pages_to_check():
        count += fix_page(title)
        if count >= limit:
            break


if __name__ == "__main__":
    main()


