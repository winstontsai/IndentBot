import re
import sys
import time

import pywikibot as pwb
import wikitextparser as wtp

def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))

def indent_text(line):
    return re.match(r'[:*#]*', line)[0]

def indent_lvl(line):
    return len(indent_text(line))

def line_content(line):
    return line[indent_lvl(line):]

def fix_gaps(lines, single_only = True, squish=True):
    """
    Remove blank lines between indented lines.

    Set single_only to True to NOT REMOVE sequences of more than one blank line.

    Set squish to True to REMOVE blank lines preceding a line with indent_lvl 1.
    """
    lines, n = list(lines), len(lines)
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

def fix_extra_indents(lines):
    """
    Fix extra indentation.
    """
    lines = list(lines)
    # fix first line
    if indent_lvl(lines[0]) > 1:
        lines[0] = lines[0][0] + line_content(lines[0])
    # fix rest of lines
    for i in range(len(lines) - 1):
        x = indent_lvl(lines[i])
        y = indent_lvl(lines[i+1])
        if y <= x + 1:
            continue
        to_remove = y - x - 1
        for j in range(i + 1, len(lines)):
            z = indent_lvl(lines[j])
            if z < y:
                break
            lines[j] = lines[j][:z - to_remove] + line_content(lines[j]) # chop off end
            #lines[j] = lines[j][to_remove:]     # chop off start
    return lines

def fix_indent_style(lines):
    """
    Do not mix indent styles. Each line's indentation style must match
    the most recently used indentation style.
    """
    new_lines = [lines[0]]     # we assume lines is nonempty
    previous_lvl = indent_lvl(lines[0])
    indent_dict = {previous_lvl: indent_text(lines[0])}

    for i, line in enumerate(lines[1:], start=1):
        lvl = indent_lvl(line)
        if lvl > previous_lvl:
            new_lines.append(new_lines[i-1][:previous_lvl] + line[previous_lvl:])
        else:
            new_lines.append(indent_dict[lvl] + line_content(line))
        indent_dict[lvl] = indent_text(new_lines[-1]) # record indentation style for this lvl
        previous_lvl = lvl
    return new_lines


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

    def not_in_bad_span(i):
        return not any(start<=i<end for start, end in bad_spans)

    borders = [0]
    for i in range(1, len(text)):
        if text[i] == '\n' and not_in_bad_span(i):
            borders.append(i + 1)
    borders.append(len(text))

    lines = []
    for i in range(len(borders) - 1):
        lines.append(text[borders[i] : borders[i + 1]])
    #print(lines)

    # The order of these fixes is important.
    # Currently, fix_indent_style relies correct indentation levels.
    lines = fix_gaps(lines, single_only = True, squish=True)
    lines = fix_extra_indents(lines)
    lines = fix_indent_style(lines)
    return ''.join(lines)


if __name__ == "__main__":
    site = pwb.Site('en', 'wikipedia')
    site.login('IndentBot')

    title = sys.argv[1]
    page = pwb.Page(site, title)

    original_text = page.text
    page.text = make_fixes(original_text)
    if page.text != original_text:
        page.save(summary='Adjusting indentation. Test.', minor=True)


