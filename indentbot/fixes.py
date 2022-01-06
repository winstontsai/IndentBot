"""
This module defines functions to fix some text.
"""
import regex as re
import wikitextparser as wtp

from patterns import (COMMENT_RE, NON_BREAKING_TAGS, PARSER_EXTENSION_TAGS,
                      SIGNATURE_PATTERN)
from patterns import in_span

################################################################################
# GAPS
################################################################################
def fix_gaps(text, squish=True):
    lines, score = line_partition(text), 0
    n = len(lines)
    # Remove certain lines with indent, but no content.
    for i in range(1, n):
        prev_line = lines[i - 1]
        m = re.match(r'([:*#]+) *\n?\Z', prev_line)
        # If level doesn't increase, just leave it.
        if not m or indent_lvl(lines[i]) <= indent_lvl(prev_line):
            continue
        # Otherwise remove it.
        lines[i - 1] = ''
        score += 1

    lines = [x for x in lines if x]
    n = len(lines)
    i = 0
    while i < n:
        txt_i, lvl_i = indent_text_lvl(lines[i])
        # don't care about non-indented lines
        if lvl_i == 0:
            i += 1; continue
        # find next non-blank line
        for j in range(i + 1, n):
            if not is_blank_line(lines[j]):
                break
        else:
            break
        txt_j, lvl_j = indent_text_lvl(lines[j])
        # closing line should be indented
        if lvl_j < 2 - squish:
            i = j; continue
        # Only remove single-line gaps for which the closing line
        # has level > 1, or for which one of
        # the opening and closing lines prefixes the other.
        if j - i != 2:
            safe_to_remove = False
        elif lvl_j > 1:
            safe_to_remove = True
        elif txt_j.startswith(txt_i) or txt_i.startswith(txt_j):
            safe_to_remove = True
        else:
            safe_to_remove = False
        if safe_to_remove:
            for k in range(i + 1, j):
                lines[k] = ''
                score += 1
        i = j
    lines = [x for x in lines if x]
    return ''.join(lines), score

################################################################################
# LEVELS
################################################################################
# def fix_levels(text, maximum=1):
#     """
#     NOT BEING USED. NOT BEING USED. NOT BEING USED. NOT BEING USED.
#     Remove over-indentation. Over-indents with more than maximum
#     extra indents are not altered.
#     """
#     lines, score = line_partition(text), 0
#     lines.insert(0, '\n') # for handling first line edge case
#     n = len(lines)
#     for i in range(n - 1):
#         l1, l2 = lines[i:i+2]
#         x, y = indent_lvl(l1), indent_lvl(l2)
#         # only remove overindentation when already inside a list
#         if x == 0:
#             continue
#         diff = y - x
#         if diff <= 1:
#             continue
#         # leave overindentation with over maximum indents
#         if diff > 1 + maximum:
#             continue
#         # check that visually it is an overindentation
#         if visual_lvl(l2) - visual_lvl(l1) <= 1:
#             continue
#         # if x and lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
#         #     diff -= 1
#         for j in range(i + 1, n):
#             l = lines[j]
#             z = indent_lvl(l)
#             if z < y:
#                 break
#             if '#' in l[x:y-1] and l[y-1] != '#':
#                 break
#             lines[j] = l[:x] + l[x + diff - 1:] # cut out l[x:y-1]
#             score += diff - 1

#     lines = lines[1:] # don't return the extra line we inserted
#     return ''.join(lines), score

################################################################################
# STYLE
################################################################################
def fix_styles(text):
    lines, score = line_partition(text), 0
    new_lines = []
    prev_lvl, prev_indent = 0, ''
    for i, line in enumerate(lines):
        old_indent, lvl = indent_text_lvl(line)
        if lvl == 0:
            new_lines.append(line)
            prev_lvl, prev_indent = 0, ''
            continue
        minlvl = min(lvl, prev_lvl)
        # Don't change style of lines starting with colons and a table,
        # but remember the style.
        if re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
            new_indent = old_indent
        else:
            new_indent = ''
            p1, p2 = 0, 0
            while p1 < minlvl and p2 < lvl:
                c1 = prev_indent[p1]
                c2 = line[p2]
                if c1 == '#':
                    if p2 < lvl - 2 and '#' not in line[p2:p2+2]:
                        new_indent += '#'
                        p2 += 1
                    else:
                        new_indent += c2
                elif c2 == '#':
                    new_indent += c2
                else:
                    new_indent += c1
                p1 += 1
                p2 += 1
            for c in line[p2:lvl]:
                # Hides any leftover floating bullets
                new_indent += ':' if c == '*' else c
        # Always keep original final indent character.
        new_indent = new_indent[:-1] + old_indent[-1]
        new_lines.append(new_indent + line[lvl:])
        if has_list_breaking_newline(line):
            prev_lvl, prev_indent = 0, ''
        else:
            prev_lvl, prev_indent = len(new_indent), new_indent
        score += new_indent != old_indent
    return ''.join(new_lines), score


# THIS VERSION (almost) ALWAYS KEEPS THE RIGHT-MOST '*' INDENT CHARACTER.
def fix_styles2(text):
    lines, score = line_partition(text), 0
    new_lines = []
    prev_lvl, prev_indent = 0, ''
    for i, line in enumerate(lines):
        old_indent, lvl = indent_text_lvl(line)
        if lvl == 0:
            new_lines.append(line)
            prev_lvl, prev_indent = 0, ''
            continue
        final_indent_char = old_indent[-1]
        last_bullet_index = old_indent.rfind('*')
        minlvl = min(lvl, prev_lvl)
        # Don't change style of lines starting with colons and a table,
        if re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
            new_indent = old_indent
        else:
            new_prefix = ''
            p1, p2 = 0, 0
            while p1 < minlvl and p2 < lvl:
                c1 = prev_indent[p1]
                c2 = line[p2]
                if c1 == '#':
                    if p2 < lvl - 2 and '#' not in line[p2:p2+2]:
                        new_prefix += '#'
                        p2 += 1
                    else:
                        new_prefix += c2
                elif c2 == '#':
                    new_prefix += c2
                elif p2 == last_bullet_index:
                    new_prefix += '*'
                else:
                    new_prefix += c1
                p1 += 1
                p2 += 1
            new_indent = new_prefix + line[p2:lvl]
            # Hide floating bullets due to abnormal level increase.
            if lvl >= prev_lvl + 2:
                last_bullet_index = new_indent.rfind('*')
                if last_bullet_index >= prev_lvl:
                    new_indent = (new_indent[:prev_lvl]
                                  + new_indent[prev_lvl:last_bullet_index].replace('*', ':')
                                  + new_indent[last_bullet_index:])
            # Set the final indent char to be the same as original.
            new_indent = new_indent[:-1] + final_indent_char

        new_lines.append(new_indent + line[lvl:])
        # Reset "memory". We intentionally forget higher level indents.
        if has_list_breaking_newline(line):
            prev_lvl, prev_indent = 0, ''
        else:
            prev_lvl, prev_indent = len(new_indent), new_indent
        score += new_indent != old_indent
    return ''.join(new_lines), score


################################################################################
# Line partitioning functions.
# Not every newline should be used to delimit a line for lists.
################################################################################
def line_partition(text):
    """
    This version better conforms to how Wikipedia treats line breaks with
    respect to lists.
    """
    wt = wtp.parse(text)
    bad_indices = set()
    for x in wt.tables + wt.templates + wt.comments:
        i, j = x.span
        bad_indices.update(find_all(text, '\n', i, j))

    for x in wt.wikilinks:
        if x.text is None:
            continue
        i, j = x.span
        bad_indices.update(find_all(text, '\n', text.index('|', i), j))

    for x in wt.parser_functions:
        i, j = x.span
        k = text.find(':', i)
        if k != -1:
            i = k
        bad_indices.update(find_all(text, '\n', i, j))

    for x in wt.get_tags():
        i, j = x.span
        if x.name in PARSER_EXTENSION_TAGS:
            bad_indices.update(find_all(text, '\n', i, j))
        else:
            close_bracket = text.index('>', i)
            bad_indices.update(find_all(text, '\n', i, close_bracket))

            open_bracket = text.rindex('<', 0, j)
            bad_indices.update(find_all(text, '\n', open_bracket, j))

    # newline followed by line consisting of spaces and comments ONLY
    for m in re.finditer(
            r'\n *{}( |{})*(?=\n)'.format(COMMENT_RE, COMMENT_RE),
            text, flags=re.S):
        bad_indices.update(find_all(text, '\n', *m.span()))

    # whitespace followed by a Category link doesn't break lines
    for m in re.finditer(
            r'(\s|{})+\[\[Category:'.format(COMMENT_RE),
            text, flags=re.I):
        bad_indices.update(find_all(text, '\n', *m.span()))

    # Now partition into lines.
    prev, lines = 0, []
    for i in find_all(text, '\n'):
        if i not in bad_indices:
            lines.append(text[prev:i + 1])
            prev = i + 1
    # Wikipedia strips newlines from the end, so add final line.
    # Even if text does have newline at the end, this is harmless since it
    # just adds an empty string.
    lines.append(text[prev:])
    return lines

################################################################################
# Helper functions
################################################################################
def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))

def indent_text(line):
    return re.match(r'[:*#]*', line)[0]

def indent_lvl(line):
    return len(indent_text(line))

def indent_text_lvl(line):
    x = indent_text(line)
    return x, len(x)

def visual_lvl(line):
    # a '#' counts for two lvls
    x = indent_text(line)
    return len(x) + x.count('#')

def has_list_breaking_newline(line):
    """
    Return True if line contains a "real" line break besides at the end.
    Basically, during line partitioning we may ignore some newlines that
    actually do break lists so that we don't edit stuff that shouldn't be
    edited, e.g. <pre></pre>. This function lets us detect such line breaks.
    """
    # pat = '\n( |' + COMMENT_RE + r')*(\{[{|]|<[^!]|\[\[(?:File|Image):)'
    # return bool(re.search(pat, line))
    wt = wtp.parse(line)
    for x in wt.get_tags():
        # if breaking tag with '\n' in contents...
        if x.name not in PARSER_EXTENSION_TAGS - NON_BREAKING_TAGS:
            continue
        if '\n' in x.contents:
            return True
    return False

def find_all(s, sub, start=0, end=None):
    """
    Yields start indices of non-overlapping instances of the substring sub in s.
    Only searches between start and end.
    """
    if end is None:
        end = len(s)
    while True:
        start = s.find(sub, start, end)
        if start == -1:
            return
        yield start
        start += len(sub)




