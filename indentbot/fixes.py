"""
This module defines functions to fix some text.
"""
import regex as re
import wikitextparser as wtp

from datetime import datetime

from pagequeue import SITE
from patterns import *


class CombinedFix:
    def __init__(
        self,
        *,
        min_closing_lvl=2,
        max_gap=1,
        allow_reset=False,
        keep_last_asterisk=False,
    ):
        """
        With the most liberal settings, essentially all gaps
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

        A gap with length greater than max_gap will not be removed.

        The parameter allow_reset, if True, means that a gap between an opening
        line with level > 1 and a closing line with level == 1 will not be
        removed.
        Note that if min_closing_lvl >= 2, then the value of the parameter
        allow_reset is irrelevant and it will effectively be True since
        gaps with a closing line of level 1 will not be removed.

        The parameter keep_last_asterisk, if True, results in the last '*' of
        an indent always being preserved.
        """
        if min_closing_lvl < 1:
            raise ValueError("min_closing_lvl should be at least 1")
        self.min_closing_lvl = min_closing_lvl
        self.max_gap = max_gap
        self.allow_reset = bool(allow_reset)
        self.keep_last_asterisk = bool(keep_last_asterisk)

    def __call__(self, text):
        lines = line_partition(text)
        if self._abort_fix(lines):
            return text, 0
        lines, score = self._adjust_indented_and_blank(lines)
        table_indices = begins_with_table(lines)
        new_lines = [lines[0]]
        prev_indent = indent_text(lines[0])
        if 0 in table_indices or has_list_breaking_newline(lines[0]):
            prev_indent = ""
        i, n = 1, len(lines)
        while i < n:
            # Find next nonblank line.
            for j in range(i, n):
                if not is_blank_line(lines[j]):
                    break
            else:
                break
            line = lines[j]
            txt_j, lvl_j = indent_text_lvl(line)

            # Compute potentially new indent.
            if j in table_indices:
                # Don't change style if starting with a table.
                new_indent = txt_j
            else:
                new_indent = self._match_indent(prev_indent, txt_j)

            # Check whether there is a gap that should be removed
            gaplen = j - i
            if gaplen == 0:
                score += new_indent != txt_j
            elif self._removable_gap(prev_indent, txt_j, new_indent, gaplen):
                if gaplen == 1:
                    new_lines += [f"{new_indent}\n"] * gaplen
                score += gaplen + (new_indent != txt_j)
            else:
                new_lines += lines[i:j]
                new_indent = txt_j
            new_lines.append(new_indent + line[lvl_j:])

            prev_indent = new_indent
            if j in table_indices or has_list_breaking_newline(line):
                prev_indent = ""
            i = j + 1
        return "".join(new_lines), score

    def _adjust_indented_and_blank(self, lines):
        """
        Adjusts lines which are indented, but otherwise have no
        content. More specifically, if the next line has a higher indentation,
        the current line is padded to match the indentation level.
        """
        score = 0
        i = len(lines) - 1
        while i > 0:
            txt, lvl = indent_text_lvl(lines[i])
            if lvl == 0:
                i -= 1
                continue
            for i in range(i - 1, -1, -1):
                p = rf"([:*#]+){SPACE_OR_COMMENT_OR_CATEGORY_RE}*\n"
                m = re.fullmatch(p, lines[i])
                if not m or len(m[1]) >= lvl:
                    break
                lines[i] = txt + lines[i][len(m[1]) :]
                score += 1
        return [x for x in lines if x], score

    def _match_indent(self, prev_indent, indent2):
        """
        Compute new indent for indent2 based on prev_indent.
        In other words, build a new indent by "matching" the indentation
        characters of the previous indent where possible.
        Either indent may be empty.

        The final indentation character is never altered.
        """
        new_indent = ""
        p1, p2 = 0, 0
        lvl = len(indent2)
        minlvl = min(len(prev_indent), lvl)
        last_ast_index = indent2.rfind("*")
        while p1 < minlvl and p2 < lvl:
            c1, c2 = prev_indent[p1], indent2[p2]
            if self.keep_last_asterisk and p2 == last_ast_index:
                new_indent += "*"
            elif c2 == "#":
                new_indent += c2
            elif c1 == "#":
                if (
                    p2 < lvl - 2
                    and indent2[p2 + 1] != "#"
                    and not (self.keep_last_asterisk and p2 + 1 == last_ast_index)
                ):
                    # can replace next two chars with '#' while keeping
                    # same indent level
                    new_indent += "#"
                    p2 += 1
                else:
                    new_indent += c2
            else:
                new_indent += c1
            p1 += 1
            p2 += 1
            # Once out-of-sync, no reason to continue matching
            if new_indent[-1] != c1:
                break
        new_indent += indent2[p2:]
        # Always keep original final indent character.
        new_indent = new_indent[:-1] + indent2[-1:]
        return new_indent

    def _removable_gap(self, opening, oldclose, newclose, gaplen):
        """
        Returns True if and only if the gap should be removed.
        """
        if gaplen < 1:
            raise ValueError("gaplen should be >= 1")
        len1, len2 = len(opening), len(newclose)
        # Only consider gaps between indented lines.
        if not (len1 and len2):
            return False
        if opening[0] != newclose[0]:
            return False
        if gaplen > self.max_gap:
            return False
        if len2 < self.min_closing_lvl:
            return False
        if self.allow_reset and len2 == 1 < len1:
            return False
        # Prevent possible numbering change.
        if one_count("", oldclose) != one_count(opening, newclose):
            return False
        return True

    def _abort_fix(self, lines):
        # Bail out in the following cases:
        # 1. There is a wikilink containing a disallowed newline,
        # and the wikilink is itself inside an indented line.
        # 2. The numbering for a numbered list might change, even if
        # the change would actually be correct.
        for i, line in enumerate(lines):
            if indent_text(line):
                wt = wtp.parse(line)
                for x in wt.wikilinks:
                    s = str(x).lstrip("[").rstrip("]")
                    if s.endswith("\n") or len(line_partition(s)) > 1:
                        return True
        # Prevent possible numbering change.
        a = indent_text(lines[0])
        for i in range(1, len(lines)):
            b = indent_text(lines[i])
            c = self._match_indent(a, b)
            if one_count(a, b) != one_count(a, c):
                return True
            a = b
        return False


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
        bad_indices.update(find_all(text, "\n", i, j))

    for x in wt.wikilinks:
        if x.text is None:
            continue
        i, j = x.span
        bad_indices.update(find_all(text, "\n", text.index("|", i), j))

    for x in wt.parser_functions:
        i, j = x.span
        k = text.find(":", i)
        if k != -1:
            i = k
        bad_indices.update(find_all(text, "\n", i, j))

    for x in wt.get_tags():
        i, j = x.span
        if x.name in PARSER_EXTENSION_TAGS:
            bad_indices.update(find_all(text, "\n", i, j))
        else:
            close_bracket = text.index(">", i)
            bad_indices.update(find_all(text, "\n", i, close_bracket))

            open_bracket = text.rindex("<", 0, j)
            bad_indices.update(find_all(text, "\n", open_bracket, j))

    # A line consisting only of spaces and 1+ comments is basically invisible
    # should be treated as part of the preceding line.
    for m in re.finditer(rf"\n *{COMMENT_RE}{SPACE_OR_COMMENT_RE}*(?=\n)", text):
        bad_indices.update(find_all(text, "\n", *m.span()))

    # Whitespace/comments followed by a Category link do not break lists
    # and are basically invisible.
    for m in re.finditer(rf"(?:\s|{COMMENT_RE})+{CATEGORY_RE}", text):
        bad_indices.update(find_all(text, "\n", *m.span()))

    # Now partition into lines.
    prev, lines = 0, []
    for i in find_all(text, "\n"):
        if i not in bad_indices:
            lines.append(text[prev : i + 1])
            prev = i + 1
    # Wikipedia strips newlines from the end, so we must explicitly
    # append the final line.
    # If text does have a newline at the end, this just appends an empty string.
    lines.append(text[prev:])
    return lines


################################################################################
# Helper functions
################################################################################
def indent_text(line):
    return re.match(r"[:*#]*", line)[0]


def indent_lvl(line):
    return len(indent_text(line))


def indent_text_lvl(line):
    x = indent_text(line)
    return x, len(x)


def is_blank_line(line):
    return bool(re.fullmatch(r"\s*", line))


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


def visual_lvl(line):
    x = indent_text(line)
    # '#' counts for two lvls visually
    return len(x) + x.count("#")


def one_count(a, b):
    """
    Given two adjacent indents a and b, counts how many instances of
    '1.' appear in b.
    """
    lena, lenb = len(a), len(b)
    j = next((i for i in range(lenb) if i >= lena or a[i] != b[i]), lenb)
    return b[j:].count("#")


def has_list_breaking_newline(line):
    """
    Return True if line contains a "real" line break besides at the end.
    Basically, during line partitioning we may ignore some newlines that
    actually do break lists so that we don't edit stuff that shouldn't be
    edited, e.g. <pre></pre>. This function lets us detect such line breaks.
    """
    wt = wtp.parse(line)
    for x in wt.get_tags():
        # if breaking tag with '\n' in contents...
        if x.name not in PARSER_EXTENSION_TAGS - NON_BREAKING_TAGS:
            continue
        if "\n" in x.contents:
            return True
    return False


def expand_list(l, title=None):
    """
    Takes a list of strings l and returns a list L such that L[i] is
    the result of expanding l[i]. REMOVES COMMENTS.
    """
    if not l:
        return []
    DELIMITER = f"INDENTBOTDELIMITERat{datetime.utcnow()}"
    z = DELIMITER.join(l)
    z = SITE.expand_text(z, title=title, includecomments=False)
    return z.split(DELIMITER)


def begins_with_table(lines):
    """
    Return a set containing the indices of lines which are both indented
    and begin with a table either using "{|" directly or through a template.
    Does not check for <table> html tags.
    """
    # return set()
    result = set()
    expand_indices = []
    expand_lines = []
    for i, line in enumerate(lines):
        lvl = indent_lvl(line)
        if lvl:
            expand_indices.append(i)
            expand_lines.append(line[lvl:])
    for ind, eline in zip(expand_indices, expand_list(expand_lines)):
        if eline.lstrip().startswith("{|"):
            result.add(ind)
    return result


if __name__ == "__main__":
    pass
