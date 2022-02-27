"""
This module defines functions to fix some text.
"""
import regex as re
import wikitextparser as wtp

from datetime import datetime

from pagequeue import SITE
from patterns import (COMMENT_RE, NON_BREAKING_TAGS, PARSER_EXTENSION_TAGS,
                      SIGNATURE_PATTERN)

################################################################################
# GAPS
################################################################################
class GapFix:
    def __init__(self, *, min_closing_lvl, max_gap_length, monotonic=True):
        """
        With the most liberal settings, all gaps (sequences of blank lines)
        between two indented lines will be removed. The parameters serve
        to prevent certain gaps from being removed.

        The parameter min_closing_lvl determines the minimum indent level
        the closing line of a gap needs to be.
        For example, if min_closing_lvl == 2, then the gap here:
            : Comment 1

            :: Comment 2

        will be removed, but the gap here:
            : Comment 1

            : Comment 2
        will not be removed.

        A gap with length greater than max_gap_length will not be removed.

        The parameter monotonic, if True, means that a gap between an opening
        line with level > 1 and a closing line with level == 1 will not be
        removed. (monotonic is somewhat of a misnomer)
        Note that if min_closing_lvl >= 2, then the value of the parameter
        monotonic is irrelevant and it will effectively be True since gaps with
        closing line having level == 1 will not be removed.
        """
        if min_closing_lvl < 1:
            raise ValueError('min_closing_lvl should be a positive integer')
        self.min_closing_lvl = min_closing_lvl
        self.max_gap_length = max_gap_length
        self.monotonic = bool(monotonic)

    def __call__(self, text):
        lines, score = self._remove_indented_and_blank(line_partition(text))
        i, n = 0, len(lines)
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
            txt_j = indent_text(lines[j])
            if self._removable_gap(txt_i, txt_j, j - i - 1):
                for k in range(i + 1, j):
                    lines[k] = ''
                    score += 1
            i = j
        lines = [x for x in lines if x]
        return ''.join(lines), score

    def _remove_indented_and_blank(self, lines):
        """
        Removes certain lines which are indented, but otherwise have no
        content. More specifically, such lines which are followed by a line
        with a higher indentation level are removed.
        Returns a new list with those lines removed, and the number of lines
        removed.
        """
        score = 0
        for i in range(1, len(lines)):
            prev_line = lines[i - 1]
            m = re.match(r'([:*#]+) *\n?\Z', prev_line)
            # If level doesn't increase, just leave it.
            if not m or indent_lvl(lines[i]) <= len(m[1]):
                continue
            lines[i - 1] = ''
            score += 1
        return [x for x in lines if x], score

    def _removable_gap(self, opening, closing, gaplen):
        """
        Opening is the opening line's indent characters.
        Closing is the closing line's indent characters.
        Gaplen is the length of the gap under consideration.
        Returns True if and only if the gap should be removed.
        """
        len1, len2 = len(opening), len(closing)
        if gaplen < 1 or gaplen > self.max_gap_length:
            return False
        if len2 < self.min_closing_lvl:
            return False
        if self.monotonic and len2 == 1 < len1:
            return False
        if len2 == 1 and closing != opening[0]:
            # never remove gap if the sole indent character of the closing
            # line does not match the opening line's first character.
            return False
        return True

################################################################################
# STYLE
################################################################################
class StyleFix:
    def __init__(self, *, hide_extra_bullets, keep_last_bullet):
        """
        The parameter hide_extra_bullets determines how "floating"
        bullets that occur inside an abnormal level increase are treated.
        Example:
            * Comment 1.
            ***: Comment 2.
        Consider the second and third bullet points of Comment 2.
        If hide_extra_bullets == 0, then they are left alone.
        If hide_extra_bullets == 1, then only the rightmost bullet is kept
            and the others (in this case just the second) get hidden.
        If hide_extra_bullets == 2, then all floating bullets inside the
            level increase, with the exception of the final indent character,
            will be hidden. In this case, this means both the second and third
            bullets will be hidden.

        So the higher the integer, the more aggressive the hiding.

        If the final indent character for Comment 2 was '*', then case 1 and 2
        would have the same behavior and both the second and third bullets
        of Comment 2 would be removed. This is because the rightmost bullet
        would be the final indent character, which is always preserved.

        The parameter keep_last_bullet, if True, results in the last '*' of
        an indent always being preserved.
        """
        if hide_extra_bullets not in range(3):
            raise ValueError('hide_extra_bullets should be in range(3)')
        if hide_extra_bullets == 2 and keep_last_bullet:
            raise ValueError(('cannot have both hide_extra_bullets == 2'
                              ' and keep_last_bullet is True'))

        self.hide_extra_bullets = hide_extra_bullets
        self.keep_last_bullet = bool(keep_last_bullet)

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
            if abort_fix(line):
                return text, 0

            if i in table_indices:
                # Don't change style if starting with a table.
                new_indent = old_indent
            else:
                new_indent = self._match_indent(prev_indent, old_indent)

            new_lines.append(new_indent + line[lvl:])
            score += new_indent != old_indent
            if i in table_indices or has_list_breaking_newline(line):
                prev_lvl, prev_indent = 0, ''
            else:
                prev_lvl, prev_indent = len(new_indent), new_indent
        return ''.join(new_lines), score

    def _match_indent(self, prev_indent, indent2):
        """
        Compute new indent for indent2 based on prev_indent.
        In other words, build a new indent by "matching" the indentation
        characters of the previous indent where possible.

        The final indentation character is never altered.
        """
        new_indent = ''
        p1, p2 = 0, 0
        lvl = len(indent2)
        minlvl = min(len(prev_indent), lvl)
        last_bullet_i = indent2.rfind('*')
        while p1 < minlvl and p2 < lvl:
            c1, c2 = prev_indent[p1], indent2[p2]
            if self.keep_last_bullet and p2 == last_bullet_i:
                new_indent += '*'
            elif c2 == '#':
                new_indent += c2
            elif c1 == '#':
                if (p2 < lvl - 2 and indent2[p2+1] != '#' and not
                    (self.keep_last_bullet and p2 + 1 == last_bullet_i)):
                    # can replace next two chars with '#' while keeping
                    # same indent level
                    new_indent += '#'
                    p2 += 1
                else:
                    new_indent += c2
            else:
                new_indent += c1
            p1 += 1
            p2 += 1
        if self.hide_extra_bullets == 2:
            for j in range(p2, lvl):
                new_indent += ':' if indent2[j] == '*' else indent2[j]
        elif self.hide_extra_bullets == 1:
            for j in range(p2, lvl):
                if j == last_bullet_i:
                    new_indent += '*'
                else:
                    new_indent += ':' if indent2[j] == '*' else indent2[j]
        else:
            new_indent += indent2[p2:]
        # Always keep original final indent character.
        new_indent = new_indent[:-1] + indent2[-1]
        return new_indent


################################################################################
# Line partitioning functions.
# Not every newline should be used to delimit a line for lists.
################################################################################
def line_partition(text):
    """
    Partition wikitext into lines, respecting how newlines interact with lists.
    The general idea is that we split on all newline characters
    except for those which either
    1. Do not break lists, or
    2. Might result in the bot editing text which should not be edited, e.g.
    text inside <pre> tags.

    In case 2, such newline characters may break lists, in contrast with
    case 1, so later we need a way to check if a line (as determined by
    this function) contains a case 2 newline character.
    This is done by the function has_list_breaking_newline.
    That way we do not perform an indent style fix incorrectly on subsequent
    lines.
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
    x = indent_text(line)
    # '#' counts for two lvls visually
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
    """
    Last resort for difficult edge cases. In these cases,
    just don't apply the fix.
    """
    # Abort if there is a wikilink containing a disallowed newline.
    wt = wtp.parse(line)
    for x in wt.wikilinks:
        s = str(x).lstrip('[').rstrip(']')
        if s.endswith('\n') or len(line_partition(s)) > 1:
            return True
    return False

def expand_list(l, title=None):
    """
    Takes a list of strings l and returns a list L such that L[i] is
    the result of expanding l[i]. REMOVES COMMENTS.
    """
    if not l:
        return []
    DELIMITER = 'INDENTBOTDELIMITERat' + str(datetime.utcnow())
    z = DELIMITER.join(l)
    z = SITE.expand_text(z, title=title, includecomments=False)
    return z.split(DELIMITER)

def begins_with_table(lines):
    """
    Return a set containing the indices of lines which are both indented
    and begin with a table either using "{|" directly or through a template.
    Does not check for <table> html tags.
    """
    result = set()
    expand_indices = []
    expand_lines = []
    for i, line in enumerate(lines):
        lvl = indent_lvl(line)
        if lvl:
            expand_indices.append(i)
            expand_lines.append(line[lvl:])
    for ind, eline in zip(expand_indices, expand_list(expand_lines)):
        if eline.lstrip('\n').startswith('{|'):
            result.add(ind)
    return result


if __name__ == "__main__":
    pass

