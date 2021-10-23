# This module defines some reusable regexes/patterns, and some helper functions.
################################################################################
import regex as re

from calendar import month_name
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

def is_subspan(x, y):
    """
    Return True if x is a subspan of y.
    """
    return y[0]<=x[0] and x[1]<=y[1]

def in_subspan(i, span):
    return span[0] <= i < span[1]

##############################################################################
# Helper functions for making regular expressions
##############################################################################
def alternates(l):
    return '(?:' + "|".join(l) + '})'

def template_pattern(name, disambiguator = ''):
    """
    Returns regex matching the specified template.
    Assumes no nested templates.
    """
    disambiguator = str(disambiguator) # used to prevent duplicate group names
    z = ''.join(x for x in name if x.isalpha())[:20] + str(len(name)) + disambiguator
    t = r'(?P<template_' + z + r'>{{(?:[^}{]|(?&template_' + z + r'))*}})'
    return r'{{\s*' + name + r'\s*(?:\|(?:[^}}{{]|{t})*)?' + '}}'

def construct_redirects(l):
    """
    Constructs the part of a regular expression which
    allows different options corresponding to the redirects listed in l.
    For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
    use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
    """
    redirects = [fr"[{x[0].upper() + x[0].lower()}]{x[1:]}" for x in l]
    return alternates(redirects)

##############################################################################
# Helper functions for templates
##############################################################################
def parse_template(template):
    """
    Takes the text of a template and
    returns the template's name and a dict of the key-value pairs.
    Unnamed parameters are given the integer keys 1, 2, 3, etc, in order.
    """
    d, counter = dict(), 1
    pieces = [x.strip() for x in template.strip('{}').split('|')]
    for piece in pieces[1:]:
        param, equals, value = piece.partition('=')
        if equals:
            d[param.rstrip()] = value.lstrip()
        else:
            d[str(counter)] = param
            counter += 1
    return (pieces[0], d)

def construct_template(name, d):
    positional = ''
    named = ''
    for k, v in sorted(d.items()):
        if re.fullmatch(r"[1-9][0-9]*", k):
            positional += "|{}".format(v)
    for k, v in d.items():
        if not re.fullmatch(r"[1-9][0-9]*", k):
            named += "|{}={}".format(k, v)
    return '{{' + name + positional + named + '}}'


##############################################################################
# Regular expressions
##############################################################################
COMMENT_RE = r'<!--(.(?<!-->))*?-->'

##############################################################################
# Storage
##############################################################################
EDIT_SUMMARY = ('Adjusted indentation. Trial edit. '
    'See [[Wikipedia:Bots/Requests for approval/IndentBot|BRFA]].')

MONTH_TO_INT = {month: i + 1 for i, month in enumerate(month_name[1:])}
SIGNATURE_PATTERN = (
    r'\[\[[Uu]ser(?: talk)?:[^\n]+?' +                  # user page link
    r'([0-2]\d):([0-5]\d), ' +                          # hh:mm
    r'([1-3]?\d) ' +                                    # day
    '(' + "|".join(m for m in MONTH_TO_INT) + ') ' +    # month name
    r'(2\d{3}) \(UTC\)'                                 # yyyy
)
# Talk, User talk, Wikipedia talk, File talk, Mediawiki talk,
# Template talk, Help talk, Category talk, Portal talk, Draft talk,
# TimedText talk, Module talk
TALK_SPACES = (1, 3, 5, 7, 11, 13, 15, 101, 119, 711, 829)
OTHER_SPACES = (4, 10)
# Wikipedia, Template
NAMESPACES = TALK_SPACES + OTHER_SPACES

BAD_PREFIXES = ('Wikipedia:Templates for discussion/', )

SANDBOXES = ('Wikipedia:Sandbox', 'Wikipedia talk:Sandbox',
    'User talk:Sandbox', 'User talk:Sandbox for user warnings',
    'Wikipedia:Articles for creation/AFC sandbox',
    'User:Sandbox')

if __name__ == "__main__":
    pass

