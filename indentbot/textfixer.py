"""
This module defines the TextFixer class which takes wikitext and
makes available the fixed wikitext, along with an error "score", as attributes.
"""
################################################################################
class TF:
    def __init__(self, *fixes, text=None):
        """
        Fixes should be callables taking one parameter, the text to be fix,
        and returning a 2-tuple consisting of fixed text and a numeric score.
        It is up to the callable what the score represents, but ideally it
        reoresents the "amount" of fixing that's been done by the callable.
        Optionally, the text parameter can be provided to immediately fix
        some text upon object initialization.
        """
        self._fixes = fixes
        if text is not None:
            self.fix(text)
        else:
            self._score = tuple()
            self._text = None
            self._original_text = None

    def fix(self, text):
        self._original_text = text
        score = []
        changed = False
        for f in self.fixes:
            text, s = f(text)
            if s:
                changed = True
            score.append(s)

        while changed:
            changed = False
            for i, f in enumerate(self.fixes):
                text, s = f(text)
                if s:
                    changed = True
                score[i] += s
        self._score = tuple(score)
        self._text = text
        return text, score

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
    def text(self):
        """
        Returns the fixed text returned by the last call to fix, or None
        if there has not been such a call.
        """
        return self._text

    @property
    def original_text(self):
        """
        Returns the text supplied to the last call to fix, or None if there has
        not been such a call.
        """
        return self._original_text

    @property
    def score(self):
        """
        Returns a tuple of the scores returned by each fix, based on the
        last call to fix. If there has not been such a call, an empty
        tuple is returned.
        """
        return self._score

    @property
    def normalized_score(self, chunksize=10000):
        """
        Represents the average total error score of a
        chunk of chunksize characters.
        """
        return chunksize * sum(self.score) / len(self.original_text)


