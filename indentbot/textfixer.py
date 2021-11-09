"""
This module defines the TextFixer class which takes wikitext and
makes available the fixed wikitext, along with an error "score", as attributes.
"""
import regex as re
import wikitextparser as wtp

from patterns import (COMMENT_RE, NON_BREAKING_TAGS, PARSER_EXTENSION_TAGS,
                      SIGNATURE_PATTERN)
from patterns import in_span

################################################################################
# Helper functions
################################################################################
def is_blank_line(line):
    return bool(re.fullmatch(r'\s+', line))


def indent_text(line):
    return re.match(r'[:*#]*', line)[0]


def indent_lvl(line):
    return len(indent_text(line))


def visual_lvl(line):
    # a '#' counts for two lvls
    x = indent_text(line)
    return len(x) + x.count('#')


def has_linebreaking_newline(line):
    # Return True if line contains a "real" line break besides at the end.
    # Considers newlines immediately preceding tables, templates, tags,
    # and File wikilinks to be real line breaks.
    pat = '\n( |' + COMMENT_RE + r')*(\{[{|]|<[^!]|\[\[(?:File|Image):)'
    return bool(re.search(pat, line))


def remove_keys_greater_than(num, d):
    for key in list(d.keys()):
        if key > num:
            del d[key]


################################################################################
# Line partitioning functions.
# Not every newline should be used to delimit a line for lists.
################################################################################
def line_partition(text):
    """
    We want to split on newline characters
    except those which satisfy at least one of the following:
    1) Editors may not want the list to break there, and they logically
        continue the same list after whatever was introduced on that line
        (usually using colon indentation)
    2) Mediawiki doesn't treat it as breaking a list.

    So, we break on all newlines EXCEPT
    1. newlines before tables
    2. newlines before templates
    3. newlines before tags
    4. newlines before File wikilinks
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
        m = re.search(r'\n( |{})*\Z'.format(COMMENT_RE), text[:i])
        if m:
            i = m.start()
        if '\n' in text[i:j]:
            bad_spans.append((i, j))

    for x in wt.comments:
        if '\n' in str(x):
            bad_spans.append(x.span)

    # newline followed by line consisting of spaces and comments ONLY
    for m in re.finditer(
            r'\n *{}( |{})*(?=\n)'.format(COMMENT_RE, COMMENT_RE),
            text, flags=re.S):
        bad_spans.append(m.span())

    # whitespace followed by a Category link doesn't break lines
    for m in re.finditer(
            r'(\s|{})+\[\[Category:'.format(COMMENT_RE),
            text, flags=re.I):
        if '\n' in m[0]:
            bad_spans.append(m.span())

    # newlines preceding links to files
    for m in re.finditer(
            r'\n( |{})*\[\[(?:File|Image):'.format(COMMENT_RE),
            text, flags=re.S):
        bad_spans.append(m.span())

    # Now partition into lines.
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c != '\n':
            continue
        if not any(in_span(i, s) for s in bad_spans):
            lines.append(text[prev:i + 1])
            prev = i + 1
    # Wikipedia strips newlines from the end, so add final line.
    # If text does have newline at the end, this is harmless since it
    # just adds an empty string.
    lines.append(text[prev:])
    return lines


def line_partition2(text):
    """
    This version better conforms to how Wikipedia treats line breaks with
    respect to lists.
    """
    wt = wtp.parse(text)
    bad_spans = []

    for x in (wt.tables + wt.templates 
              + wt.comments + wt.wikilinks + wt.parser_functions):
        if '\n' in str(x):
            bad_spans.append(x.span)
    for x in wt.get_tags():
        i, j = x.span

        close_bracket = text.index('>', i)
        if '\n' in text[i : close_bracket]:
            bad_spans.append((i, close_bracket))

        open_bracket = text.rindex('<', 0, j)
        if '\n' in text[open_bracket : j]:
            bad_spans.append((open_bracket, j))

        if x.name not in PARSER_EXTENSION_TAGS:
            continue
        if '\n' in str(x):
            bad_spans.append(x.span)

    # newline followed by line consisting of spaces and comments ONLY
    for m in re.finditer(
            r'\n *{}( |{})*(?=\n)'.format(COMMENT_RE, COMMENT_RE),
            text, flags=re.S):
        bad_spans.append(m.span())

    # whitespace followed by a Category link doesn't break lines
    for m in re.finditer(
            r'(\s|{})+\[\[Category:'.format(COMMENT_RE),
            text, flags=re.I):
        if '\n' in m[0]:
            bad_spans.append(m.span())

    # Now partition into lines.
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c != '\n':
            continue
        if not any(in_span(i, s) for s in bad_spans):
            lines.append(text[prev:i + 1])
            prev = i + 1
    # Wikipedia strips newlines from the end, so add final line.
    # If text does have newline at the end, this is harmless since it
    # just adds an empty string.
    lines.append(text[prev:])
    return lines


################################################################################
# Base TextFixer class. Fixes text and makes the fixed text and "error score"
# available as attributes.
################################################################################
class TextFixer:
    def __init__(self, text):
        self.fix(text)

    def fix(self, text):
        self._original_text = text
        self._lines = line_partition2(text)
        a, b, c, d = self._fix_gaps(), self._fix_levels(), *self._fix_styles()
        score = [a, b, c, d]
        while any((a, b, c, d)):
            a, b, c, d = self._fix_gaps(), self._fix_levels(), *self._fix_styles()
            score[0] += a
            score[1] += b
            score[2] += c
            score[3] += d
        self._score = tuple(score)

    def __str__(self):
        return ''.join(self._lines)

    @property
    def text(self):
        return str(self)

    @property
    def original_text(self):
        return self._original_text

    @property
    def score(self):
        return self._score

    @property
    def normalized_score(self):
        """
        Represents the average total error score of a
        chunk of 10,000 characters from the original text.
        """
        return 10000 * sum(self.score) / len(self.original_text)

    # NOT BEING USED
    # def _fix_levels(self, maximum=1):
    #     """
    #     Remove over-indentation. Over-indents with more than maximum
    #     extra indents are not altered.
    #     """
    #     score = 0
    #     lines = self._lines
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

    #     self._lines = lines[1:] # don't return the extra line we inserted
    #     return score



################################################################################
# VERSION TWO
# Used for testing improvements.
################################################################################
class TextFixerTWO(TextFixer):
    def _fix_gaps(self, squish=True):
        score = 0
        lines = self._lines
        n = len(lines)
        # Remove lines with indent but no content.
        for i in range(n):
            m = re.match(r'([:*#]+) *\n?\Z', lines[i])
            if m:
                # If level doesn't increase after, just leave it.
                if i + 1 < n and indent_lvl(lines[i + 1]) <= len(m[1]):
                    continue
                # Otherwise remove it.
                lines[i] = ''
                score += 1
        lines = [x for x in lines if x]
        n = len(lines)

        i = 0
        while i < n:
            txt_i = indent_text(lines[i])
            lvl_i = len(txt_i)
            # don't care about non-indented lines
            if lvl_i == 0:
                i += 1
                continue
            # find next non-blank line
            j = i + 1
            while j < n:
                if is_blank_line(lines[j]):
                    j += 1
                    continue
                break
            if j == n:
                break
            txt_j = indent_text(lines[j])
            lvl_j = len(txt_j)
            # closing line should be indented
            if lvl_j >= 2 - squish:
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
        self._lines = [x for x in lines if x]
        return score

    def _fix_levels(self):
        return 0

    def _fix_styles(self):
        """
        Fixes mixed indent styles.
        """
        lines = self._lines
        num_lines = len(lines)

        final_indent = [None] * num_lines
        for i, line in enumerate(lines):
            itxt = indent_text(line)
            z = len(itxt)
            if z == 0:
                continue
            # Don't change final indent character at all.
            final_indent[i] = itxt[-1]

        # At this point, the final indentation character for every line
        # should have been determined and is stored in final_indent.
        score, score_final = 0, 0
        new_lines, prev_lvl, indent_dict = [], 0, {0: ''}
        for i, line in enumerate(lines):
            old_indent = indent_text(line)
            lvl = len(old_indent)
            if lvl == 0:
                new_lines.append(line)
                prev_lvl = 0
                indent_dict = {0: ''}
                continue
            minlvl = min(lvl, prev_lvl)
            # necessary for edge cases
            minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

            # Don't change style of lines starting with colons and a table,
            # but remember the style.
            if re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
                new_indent = old_indent
            else:
                new_prefix = ''
                p1, p2 = 0, 0
                while p1 < minlvl and p2 < lvl:
                    c1 = indent_dict[minlvl][p1]
                    c2 = line[p2]
                    if c1 == '#':
                        if p2 <= lvl - 3 and '#' not in line[p2:p2+2]:
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
                # Hide floating bullets
                if lvl >= prev_lvl + 2:
                    new_indent = new_indent[:prev_lvl] + new_indent[prev_lvl:].replace('*', ':')
                # Set the final indent char
                new_indent = new_indent[:-1] + final_indent[i]

            new_lines.append(new_indent + line[lvl:])
            new_lvl = len(new_indent)
            indent_dict[new_lvl] = new_indent
            # Reset "memory". We intentionally forget higher level indents.
            if new_lvl < prev_lvl:
                remove_keys_greater_than(new_lvl, indent_dict)
            prev_lvl = new_lvl
            score += new_indent != old_indent
            score_final += new_indent[-1] != old_indent[-1]
        self._lines = new_lines
        return score, score_final


class TextFixerTHREE(TextFixerTWO):
    pass

