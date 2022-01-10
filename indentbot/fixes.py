"""
This module defines functions to fix some text.
"""
import regex as re
import wikitextparser as wtp

from pagequeue import SITE

from patterns import (COMMENT_RE, NON_BREAKING_TAGS, PARSER_EXTENSION_TAGS,
                      SIGNATURE_PATTERN)

################################################################################
# GAPS
################################################################################
class GapFix:
    def __init__(self, min_closing_lvl=1, single_only=True, monotonic=True):
        """
        The parameter min_closing_lvl determines the minimum indent level
        the closing line of a gap needs to be to have the gap removed.

        For example, if min_closing_lvl == 2, then the gap here:
        : Comment 1

        :: Comment 2

        will be removed, but the gap here:
        : Comment 1

        : Comment 2

        will not be removed.

        The parameter single_only, if True, means that only length 1 gaps
        are removed.

        The parameter monotonic, if True, means that a gap between an opening
        line with level > 1 and a closing line with level == 1 will not be
        removed, e.g. the gap here:
        * Comment 1
        ** Comment 2

        * Comment 3

        will not be removed.
        """
        if min_closing_lvl < 1:
            raise ValueError('min_closing_lvl must be at least 1')
        self.min_closing_lvl = min_closing_lvl
        self.single_only = single_only
        self.monotonic = monotonic

    def __call__(self, text):
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
            if self.single_only and j - i != 2:
                pass
            elif lvl_j < self.min_closing_lvl:
                pass
            elif self.monotonic and 1 == lvl_j < lvl_i:
                pass
            elif lvl_j == 1 and txt_j != txt_i[0]:
                # never remove gap if the sole indent character of the closing
                # line does not match the opening line's first character.
                pass
            else:
                for k in range(i + 1, j):
                    lines[k] = ''
                    score += 1
            i = j
        lines = [x for x in lines if x]
        return ''.join(lines), score


################################################################################
# STYLE
################################################################################
class StyleFix:
    def __init__(self, hide_extra_bullets=0):
        """
        The parameter hide_extra_bullets determines how "floating"
        bullets that occur inside an abnormal level increase are treated.
        Example:

        * Comment 1.
        ***: Comment 2.

        Consider the second and third bullets of Comment 2.
        If hide_extra_bullets == 0, then they are left alone.
        If hide_extra_bullets == 1, then only the rightmost bullet is kept,
            so only the second bullet is hidden.
        If hide_extra_bullets == 2, then both the second and third bullets
            are hidden.

        If the final indent character for Comment 2 was '*', then 1 and 2
        will have the same behavior and both the second and third bullets
        of Comment 2 would be removed. This is because the rightmost bullet
        would be the final indent character, which is always preserved.
        """
        self.hide_extra_bullets = hide_extra_bullets

    def __call__(self, text):
        lines, score = line_partition(text), 0
        table_indices = begins_with_table(lines)
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
            if i in table_indices:
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
                if self.hide_extra_bullets == 2:
                    for j in range(p2, lvl):
                        new_indent += ':' if line[j] == '*' else line[j]
                elif self.hide_extra_bullets == 1:
                    last_bullet_index = old_indent.rfind('*')
                    for j in range(p2, lvl):
                        if j == last_bullet_index:
                            new_indent += '*'
                        elif line[j] == '*':
                            new_indent += ':'
                        else:
                            new_indent += line[j]
                else:
                    new_indent += line[p2:lvl]
            # Always keep original final indent character.
            new_indent = new_indent[:-1] + old_indent[-1]
            new_lines.append(new_indent + line[lvl:])
            if i in table_indices or has_list_breaking_newline(line):
                prev_lvl, prev_indent = 0, ''
            else:
                prev_lvl, prev_indent = len(new_indent), new_indent
            if abort_fix(line):
                return text, 0
            score += new_indent != old_indent
        return ''.join(new_lines), score


# THIS VERSION (almost) ALWAYS KEEPS THE RIGHT-MOST '*' CHARACTER.
# def fix_styles3(text):
#     lines, score = line_partition(text), 0
#     new_lines = []
#     prev_lvl, prev_indent = 0, ''
#     for i, line in enumerate(lines):
#         old_indent, lvl = indent_text_lvl(line)
#         if lvl == 0:
#             new_lines.append(line)
#             prev_lvl, prev_indent = 0, ''
#             continue
#         minlvl = min(lvl, prev_lvl)
#         last_bullet_index = old_indent.rfind('*')
#         # Don't change style of lines starting with colons and a table,
#         # but remember the style.
#         if re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
#             new_indent = old_indent
#         else:
#             new_indent = ''
#             p1, p2 = 0, 0
#             while p1 < minlvl and p2 < lvl:
#                 c1 = prev_indent[p1]
#                 c2 = line[p2]
#                 if c1 == '#':
#                     if p2 < lvl - 2 and '#' not in line[p2:p2+2]:
#                         new_indent += '#'
#                         p2 += 1
#                     else:
#                         new_indent += c2
#                 elif c2 == '#':
#                     new_indent += c2
#                 elif p2 == last_bullet_index:
#                     new_indent += '*'
#                 else:
#                     new_indent += c1
#                 p1 += 1
#                 p2 += 1
#             for j in range(p2, lvl):
#                 if j == last_bullet_index:
#                     new_indent += '*'
#                 else:
#                     new_indent += ':' if line[j] == '*' else line[j]
#         # Always keep original final indent character.
#         new_indent = new_indent[:-1] + old_indent[-1]
#         new_lines.append(new_indent + line[lvl:])
#         if has_list_breaking_newline(line):
#             prev_lvl, prev_indent = 0, ''
#         else:
#             prev_lvl, prev_indent = len(new_indent), new_indent
#         score += new_indent != old_indent
#     return ''.join(new_lines), score


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
    #print(lines)
    return lines

################################################################################
# Helper functions
################################################################################
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

def abort_fix(line):
    # Abort if there is a wikilink containing a disallowed newline.
    wt = wtp.parse(line)
    for x in wt.wikilinks:
        if len(line_partition(str(x).lstrip('[').rstrip(']'))) > 1:
            #print(line)
            return True
    return False

def expand_list(l, title=None):
    """
    Takes a list of strings l and returns a list L such that L[i] is
    the result of expanding l[i]. REMOVES COMMENTS.
    """
    if not l:
        return []
    DELIMITER = '\nzaaaaaINDENTBOT DELIMITERaaaaaaz\n'
    z = DELIMITER.join(l)
    z = SITE.expand_text(z, title=title, includecomments=False)
    z = z.split(DELIMITER)
    return [z[i] for i in range(len(l))]

def begins_with_table(lines):
    """
    Return a set containing the indices of lines which are both indented
    and begin with a table either using "{|" directly or through a template.
    Does not check for <table> html tags.
    """
    answer = set()
    expand_indices = []
    expand_lines = []
    for i, line in enumerate(lines):
        lvl = indent_lvl(line)
        if lvl:
            expand_indices.append(i)
            expand_lines.append(line[lvl:])
    expand_lines = expand_list(expand_lines)
    for ind, eline in zip(expand_indices, expand_lines):
        if eline.lstrip().startswith('{|'):
            answer.add(ind)
    return answer


if __name__ == "__main__":
    pass


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


