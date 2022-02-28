"""
This module defines the TextFixer class which takes wikitext and
makes available the fixed wikitext, along with an error "score", as attributes.
"""
################################################################################
class TextFixer:
    def __init__(self, *fixes):
        """
        fixes should be callables taking one parameter, the text to be fix,
        and returning a 2-tuple consisting of fixed text and a
        nonnegative numeric score.
        It is up to the callable what the score represents, but ideally it
        reoresents the "amount" of fixing that's been done by the callable.
        Optionally, the text parameter can be provided to immediately fix
        some text upon object initialization.
        """
        if not fixes:
            raise ValueError('no fixes provided')
        if any(not callable(f) for f in fixes):
            raise TypeError('all fixes must be callable')
        self._fixes = fixes
        self._fix_count = 0

    def fix(self, text):
        self._fix_count += 1
        self._original_text = text
        score = [0] * len(self.fixes)
        while True:
            changed = False
            for i, f in enumerate(self.fixes):
                text, s = f(text)
                if s:
                    score[i] += s
                    changed = True
            if not changed:
                break
        score = tuple(score)
        self._text, self._score = text, score
        return text, score

    def _fixed(self):
        return self._fix_count != 0

    def __str__(self):
        return self._text

    def __bool__(self):
        return any(self.score)

    @property
    def fixes(self):
        return self._fixes

    @fixes.setter
    def fixes(self, *fixes):
        self._fixes = fixes

    @property
    def original_text(self):
        """
        Returns the text supplied to the last call to fix.
        """
        if not self._fixed():
            raise AttributeError("fix has not yet been called.")
        return self._original_text

    @property
    def text(self):
        """
        Returns the fixed text returned by the last call to fix.
        """
        if not self._fixed():
            raise AttributeError("fix has not yet been called.")
        return self._text

    @property
    def score(self):
        """
        Returns the score tuple returned by the last call to fix.
        """
        if not self._fixed():
            raise AttributeError("fix has not yet been called.")
        return self._score

    @property
    def total_score(self):
        return sum(self.score)

    @property
    def normalized_score(self):
        """
        Returns the total score divided by the length of the original text.
        """
        return self.total_score / len(self.original_text)

