import re
import sys
import time

import pywikibot as pwb
import wikitextparser as wtp

def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))

def indent_text(line):
    return re.match(r'[:*]*', line)[0]

def indent_lvl(line):
    return len(indent_text(line))

def fix_gaps(lines, single_only = True, squish=True):
    """
    Remove blank lines between indented lines.

    Set single_only to True to NOT REMOVE sequences of more than one blank line.

    Set squish to True to REMOVE blank lines preceding a line with indent_lvl 1.
    """
    n = len(lines)
    lines = list(lines)
    DELETE_MARKER = 'gonna delete this lineeeeeeeeeeeeeeeeee'
    i = 0
    while i < n:
        if indent_lvl(lines[i]):
            j = i + 1
            while j < n and is_blank_line(lines[j]):
                j += 1
                if single_only:
                    break
            if j < n and indent_lvl(lines[j]) >= 2 - squish:
                for k in range(i + 1, j):
                    lines[k] = DELETE_MARKER
            i = j
        else:
            i += 1
    return [x for x in lines if x != DELETE_MARKER]

def fix_indent_style(lines):
    """
    Do not mix indent styles. This function iterates over
    pairs of lines (say, A and B) from beginning to end, and
    ensures that either indent_text(A) prefixes B or that
    indent_text(B) prefixes A by modifying the indent text of line B
    without changing its indent level.
    """
    new_lines = [lines[0]]
    for i in range(0, len(lines)-1):
        x, y = indent_lvl(new_lines[i]), indent_lvl(lines[i+1])
        z = min(x, y)
        new_lines.append(new_lines[i][:z] + lines[i+1][z:])
    return new_lines

def fix_extra_indents(lines):
    """
    Fix extra indentation.
    """
    lines = list(lines)
    for i in range(len(lines) - 1):
        x = indent_lvl(lines[i])
        y = indent_lvl(lines[i+1])
        if y <= x + 1:
            continue
        difference = y - x
        for j in range(i + 1, len(lines)):
            z = indent_lvl(lines[j])
            if z < y:
                break
            lines[j] = lines[j][:z-difference+1] + lines[j][z:]
    return lines

def make_fixes(text):
    wikitext = wtp.parse(text)

    bad_spans = []
    for x in wikitext.comments:
        if '\n' in str(x):
            bad_spans.append(x.span)

    for x in wikitext.templates:
        if wikitext.string[:x.span[0]].endswith('\n'):
            bad_spans.append( (x.span[0]-1, x.span[1]) )
        elif '\n' in str(x):
            bad_spans.append(x.span)

    for x in wikitext.get_tags():
        if wikitext.string[:x.span[0]].endswith('\n'):
            bad_spans.append( (x.span[0]-1, x.span[1]) )
        elif '\n' in str(x):
            bad_spans.append(x.span)

    def in_bad_span(i):
        return any(start<=i<end for start, end in bad_spans)

    borders = [0]
    for i in range(1, len(text)):
        if text[i] == '\n' and not in_bad_span(i):
            borders.append(i + 1)
    if borders[-1] != len(text):
        borders.append(len(text))

    lines = []
    for i in range(len(borders) - 1):
        lines.append(text[borders[i] : borders[i + 1]])

    #print(lines)

    lines = fix_gaps(lines, single_only = True, squish=True)
    lines = fix_indent_style(lines)
    lines = fix_extra_indents(lines)
    return ''.join(lines)



if __name__ == "__main__":
    site = pwb.Site('en', 'wikipedia')
    site.login()

    title = sys.argv[1]
    page = pwb.Page(site, title)
    original_text = page.text
    page.text = make_fixes(original_text)

    if page.text != original_text:
        page.save(summary='Adjusting indentation. Test.', minor=True)

