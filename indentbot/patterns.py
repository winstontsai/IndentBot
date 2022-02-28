"""
This module defines some utilities and constants.
"""
from calendar import month_name, month_abbr

import pywikibot as pwb
import regex as re

################################################################################
def pattern_count(pattern, text, flags=0):
    return sum(1 for x in re.finditer(pattern, text, flags))


def find_pattern(pattern, text, start=0, end=None, flags=0):
    if end is None:
        end = len(text)
    pattern = re.compile(pattern, flags)
    m = pattern.search(text, start, end)
    if m:
        return m.start()
    return -1


def rfind_pattern(pattern, text, start=0, end=None, flags=0):
    if end == None:
        end = len(text)
    pattern = re.compile(pattern, flags=flags|re.REVERSE)
    m = pattern.search(text, start, end)
    if m:
        return m.start()
    return -1


def index_pattern(pattern, text, start=0, end=None, flags=0):
    i = find_pattern(pattern, text, start, end, flags)
    if i == -1:
        raise ValueError('substring not found')
    return i


def rindex_pattern(pattern, text, start=0, end=None, flags=0):
    i = rfind_pattern(pattern, text, start, end, flags)
    if i == -1:
        raise ValueError('substring not found')
    return i


def diff_template(page, label=None):
    """
    Return a Template:Diff2 string for the given Page.
    """
    x = '{{Diff2|' + str(page.latest_revision_id)
    if label is None:
        x += '|' + page.title()
    else:
        x += '|' + label
    return x + '}}'


def set_status_page(status):
    page = pwb.Page(pwb.Site('en', 'wikipedia'), 'User:IndentBot/status')
    page.text = status
    page.save(summary='Updating status: {}'.format(status),
              minor=True,
              botflag=True,
              quiet=True,)


################################################################################
# Regular expressions
################################################################################
COMMENT_RE = r'<!--(.(?<!-->))*?-->'

################################################################################
# Constants
################################################################################
MAINTAINERS = frozenset(['IndentBot', 'Notsniwiast'])

SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser(?: talk)?:[^\n]+?' +                  # user page link
    r'([0-2]\d):([0-5]\d), ' +                          # hh:mm
    r'([1-3]?\d) ' +                                    # day
    '(' + '|'.join(month_name[1:] + month_abbr[1:]) + ') ' +  # month name
    r'(2\d{3}) \(UTC\)'                                 # yyyy
)

PARSER_EXTENSION_TAGS = frozenset(['gallery', 'includeonly', 'noinclude',
    'nowiki', 'onlyinclude', 'pre',
    'categorytree', 'charinsert', 'chem', 'ce', 'graph', 'hiero', 'imagemap',
    'indicator', 'inputbox', 'langconvert', 'mapframe', 'maplink', 'math',
    'math chem',
    'poem', 'ref', 'references', 'score', 'section', 'syntaxhighlight',
    'source', 'templatedata', 'templatestyles', 'timeline'
    ])


"""Does a newline in this thing break a list? As determined by
* Hi <tag>
Some stuff</tag>
** Bye.

???
If NO, then we shouldn't split on newlines inside them.
If YES, then we SHOULD split on newlines inside them

NEWLINES IN THESE THINGS DO NOT BREAK LISTS:
comments, templates, gallery, includeonly, nowiki, categorytree, chem, ce,
graph, heiro, imagemap, indicator, inputbox, mapframe, maplink, math,
math chem, ref, score, syntaxhighlight, source, templatedata, 
"""
NON_BREAKING_TAGS = frozenset(['gallery', 'includeonly', 'nowiki',
    'categorytree', 'chem', 'ce', 'graph', 'hiero', 'imagemap', 'indicator',
    'inputbox', 'mapframe', 'maplink', 'math', 'math chem', 'ref', 'score',
    'syntaxhighlight', 'source', 'templatedata'])


if __name__ == "__main__":
    pass

