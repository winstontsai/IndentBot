"""
This module defines the TextFixer class which takes wikitext and
makes available the fixed wikitext, along with an error "score", as attributes.
"""
import regex as re
import wikitextparser as wtp

from patterns import COMMENT_RE, in_span

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


def bulleted_or_unbulleted(lines, level):
    """
    Helper function for TextFixer._fix_styles.
    This function basically counts how many lines of the given level (which
    should be greater than 0),
    starting from the first line and continuing until a line with smaller level
    is reached, use '*' or ':' as the final indentation character.
    It returns the character that wins the count, preferring '*'
    when there is a tie.
    """
    bulleted = 0
    unbulleted = 0
    for line in lines:
        s = indent_text(line)
        lvl = len(s)
        if lvl < level:
            break
        elif lvl == level:
            if s[-1] == ':':
                unbulleted += 1
            elif s[-1] == '*':
                bulleted += 1
    return '*' if bulleted >= unbulleted else ':'


################################################################################
# Line partitioning functions.
# Not every newline should be used to delimit a line for lists.
################################################################################
def get_bad_spans(text):
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
        if x.parent():
            continue
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

    return bad_spans


def line_partition(text):
    bad_spans = get_bad_spans(text)
    prev, lines = 0, []
    for i, c in enumerate(text):
        if c != '\n':
            continue
        if all(not in_span(i, s) for s in bad_spans):
            lines.append(text[prev:i + 1])
            prev = i + 1
    # Since Wikipedia strips newlines from the end, add final line.
    lines.append(text[prev:])
    return lines


################################################################################
# TextFixer class. Fixes text and makes the fixed text and "error score"
# available as attributes.
################################################################################
class TextFixer:
    def __init__(self, text):
        self.fix(text)

    def fix(self, text):
        self._original_text = text
        self._lines = line_partition(text)
        a, b, c, d = self._fix_gaps(), self._fix_levels(), *self._fix_styles()
        score = [a, b, c, d]
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
        """
        A 3-tuple (a, b, c), where, roughly,
        a is the number of blank lines removed
        b is the amount of extra indentation removed
        c is the number of indent styles changed
        """
        return self._score

    @property
    def normalized_score(self):
        """
        Represents the average total error score of a
        chunk of 10,000 characters from the original text.
        """
        return 10000 * sum(self.score) / len(self.original_text)

    def _fix_gaps(self, squish=True, single_only=False):
        """
        Remove gaps sandwiched indented lines.
        A gap is a sequence of blank lines.
        Set squish to False to KEEP blank lines preceding a lvl 1 line.
        Set single_only to False to remove certain multi-line gaps.

        Currently if the opening or closing line of a gap starts with '#',
        the gap is not removed.
        Otherwise, length 1 gaps are removed, and multiline gaps are
        removed only if the closing line has lvl >= 2.
        """
        score = 0
        lines = self._lines
        i, n = 0, len(lines)
        while i < n:
            txt_i = indent_text(lines[i])
            lvl_i = len(txt_i)
            # don't care about non-indented lines
            if lvl_i == 0 or has_linebreaking_newline(lines[i]):
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
            if lvl_j >= 2 - squish:
                if txt_j.startswith(txt_i) or txt_i.startswith(txt_j):
                    safe_to_remove = True
                elif j - i == 2:
                    safe_to_remove = True
                elif lvl_j > 1:
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
        """
        Remove over-indentation.
        """
        score = 0
        lines = self._lines
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
            # if x and lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
            #     diff -= 1
            for j in range(i + 1, n):
                l = lines[j]
                if indent_lvl(l) < y:
                    break
                if '#' in l[x:y-1]:
                    break
                lines[j] = l[:x] + l[x + diff - 1:] # cut out l[x:y-1]
                score += diff - 1

        self._lines = lines[1:] # don't return the extra line we inserted
        return score

    def _fix_styles(self):
        """
        Do not mix indent styles. Each line's indentation style must match
        the (roughly) most recently used indentation style.
        """
        score, score_final = 0, 0
        new_lines, prev_lvl, indent_dict = [], 0, {0: ''}
        for i, line in enumerate(self._lines):
            old_indent = indent_text(line)
            lvl = len(old_indent)
            if lvl == 0:
                new_lines.append(line)
                prev_lvl = 0
                indent_dict = {0: ''}
                continue
            minlvl = min(lvl, prev_lvl)
            # necessary when using certain strategies to fix indentation lvls
            minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

            # Don't change style if it's a small note indented with a colon.
            if re.match(r': ?<small[^>]*> ?Note:', line):
                new_indent = old_indent
            # Don't change style of lines starting with colons and a table,
            # but remember the style, with the exception that a '*' first char
            # is preserved.
            elif re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
                new_indent = old_indent
                if indent_dict[minlvl].startswith('*'):
                    indent_dict[lvl] = '*' + old_indent[1:]
                else:
                    indent_dict[lvl] = old_indent
            else:
                # Determine what last char should be.
                # When level doesn't increase, it remains the same.
                # When level increases, we choose bullet or no bullet
                # so that subsequent lines with the same
                # level (before a "reset")
                # will use the most common type (bullet or no bullet).
                need_to_set_last_char = False
                if lvl > prev_lvl and old_indent[-1] != '#':
                    need_to_set_last_char = True
                    last_char = bulleted_or_unbulleted(self._lines[i:], lvl)
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
                # set the last char, see above
                if need_to_set_last_char:
                    new_indent = new_indent[:-1] + last_char
                indent_dict[len(new_indent)] = new_indent

            new_lines.append(new_indent + line[lvl:])
            new_lvl = len(new_indent)
            # Reset "memory". We intentionally forget higher level indents.
            if has_linebreaking_newline(new_lines[-1]):
                indent_dict = {0: ''}
            elif new_lvl < prev_lvl:
                for key in list(indent_dict.keys()):
                    if key > new_lvl:
                        del indent_dict[key]
            prev_lvl = new_lvl

            score += new_indent != old_indent
            score_final += new_indent[-1] != old_indent[-1]

        self._lines = new_lines
        return score, score_final



################################################################################
# VERSION TWO
# Used for testing improvements.
################################################################################
class TextFixerTWO:
    def __init__(self, text):
        self.fix(text)

    def fix(self, text):
        self._original_text = text
        self._lines = line_partition(text)
        a, b, c, d = self._fix_gaps(), self._fix_levels(), *self._fix_styles()
        score = [a, b, c, d]
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
        """
        A 3-tuple (a, b, c), where, roughly,
        a is the number of blank lines removed
        b is the amount of extra indentation removed
        c is the number of indent styles changed
        """
        return self._score

    @property
    def normalized_score(self):
        """
        Represents the average total error score of a
        chunk of 10,000 characters from the original text.
        """
        return 10000 * sum(self.score) / len(self.original_text)

    def _fix_gaps(self, squish=True, single_only=False):
        """
        Remove gaps sandwiched indented lines.
        A gap is a sequence of blank lines.
        Set squish to False to KEEP blank lines preceding a lvl 1 line.
        Set single_only to False to remove certain multi-line gaps.

        Currently if the opening or closing line of a gap starts with '#',
        the gap is not removed.
        Otherwise, length 1 gaps are removed, and multiline gaps are
        removed only if the closing line has lvl >= 2.
        """
        score = 0
        lines = self._lines
        i, n = 0, len(lines)
        while i < n:
            txt_i = indent_text(lines[i])
            lvl_i = len(txt_i)
            # don't care about non-indented lines
            if lvl_i == 0 or has_linebreaking_newline(lines[i]):
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
            if lvl_j >= 2 - squish:
                if txt_j.startswith(txt_i) or txt_i.startswith(txt_j):
                    safe_to_remove = True
                elif j - i == 2:
                    safe_to_remove = True
                elif lvl_j > 1:
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
        """
        Remove over-indentation.
        """
        score = 0
        lines = self._lines
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
            # if x and lines[i][x-1]=='#' and lines[i+1][y-1] != ':':
            #     diff -= 1
            for j in range(i + 1, n):
                l = lines[j]
                if indent_lvl(l) < y:
                    break
                if '#' in l[x:y-1]:
                    break
                lines[j] = l[:x] + l[x + diff - 1:] # cut out l[x:y-1]
                score += diff - 1

        self._lines = lines[1:] # don't return the extra line we inserted
        return score

    def _fix_styles(self):
        """
        Do not mix indent styles. Each line's indentation style must match
        the (roughly) most recently used indentation style.
        """
        score, score_final = 0, 0
        new_lines, prev_lvl, indent_dict = [], 0, {0: ''}
        for i, line in enumerate(self._lines):
            old_indent = indent_text(line)
            lvl = len(old_indent)
            if lvl == 0:
                new_lines.append(line)
                prev_lvl = 0
                indent_dict = {0: ''}
                continue
            minlvl = min(lvl, prev_lvl)
            # necessary when using certain strategies to fix indentation lvls
            minlvl = next(k for k in range(minlvl, -1, -1) if k in indent_dict)

            # Don't change style if it's a small note indented with a colon.
            if re.match(r': ?<small[^>]*> ?Note:', line):
                new_indent = old_indent
            # Don't change style of lines starting with colons and a table,
            # but remember the style, with the exception that a '*' first char
            # is preserved.
            elif re.match(r':*( |' + COMMENT_RE + r')*\{\|', line):
                new_indent = old_indent
                if indent_dict[minlvl].startswith('*'):
                    indent_dict[lvl] = '*' + old_indent[1:]
                else:
                    indent_dict[lvl] = old_indent
            else:
                # Determine what last char should be.
                # When level doesn't increase, it remains the same.
                # When level increases, we choose bullet or no bullet
                # so that subsequent lines with the same
                # level (before a "reset")
                # will use the most common type (bullet or no bullet).
                need_to_set_last_char = False
                if lvl > prev_lvl and old_indent[-1] != '#':
                    need_to_set_last_char = True
                    last_char = bulleted_or_unbulleted(self._lines[i:], lvl)
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
                # set the last char, see above
                if need_to_set_last_char:
                    new_indent = new_indent[:-1] + last_char
                indent_dict[len(new_indent)] = new_indent

            new_lines.append(new_indent + line[lvl:])
            new_lvl = len(new_indent)
            # Reset "memory". We intentionally forget higher level indents.
            if has_linebreaking_newline(new_lines[-1]):
                indent_dict = {0: ''}
            elif new_lvl < prev_lvl:
                for key in list(indent_dict.keys()):
                    if key > new_lvl:
                        del indent_dict[key]
            prev_lvl = new_lvl

            score += new_indent != old_indent
            score_final += new_indent[-1] != old_indent[-1]

        self._lines = new_lines
        return score, score_final


