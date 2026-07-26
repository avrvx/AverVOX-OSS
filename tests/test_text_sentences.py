"""The sentence splitter shared by the LLM stream and the speech pipeline."""

import pytest

from avervox.text import iter_sentences, split_sentences


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self):
        assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]

    def test_keeps_a_trailing_fragment(self):
        assert split_sentences("Done. And then") == ["Done.", "And then"]

    def test_breaks_on_colons_and_semicolons(self):
        """Coarse on purpose: short utterances sound better than long ones."""
        assert split_sentences("Listen: here it is; ready?") == [
            "Listen:",
            "here it is;",
            "ready?",
        ]

    def test_a_decimal_point_does_not_split(self):
        """The regex needs whitespace after the punctuation, which is why."""
        assert split_sentences("It costs 3.50 today.") == ["It costs 3.50 today."]

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_input_yields_nothing(self, text):
        assert split_sentences(text) == []

    def test_text_with_no_punctuation_is_one_chunk(self):
        assert split_sentences("no punctuation here") == ["no punctuation here"]


class TestIterSentences:
    def test_yields_before_the_stream_ends(self):
        """The whole point: speech starts before the LLM has finished writing."""
        tokens = iter(["Hello", " there", ". ", "Still", " typing"])
        stream = iter_sentences(tokens)

        assert next(stream) == "Hello there."
        # The generator has not consumed the rest yet.
        assert next(stream) == "Still typing"

    def test_a_sentence_split_across_many_tokens(self):
        assert list(iter_sentences(["Th", "is ", "is ", "one", ". "])) == [
            "This is one."
        ]

    def test_several_sentences_in_one_token(self):
        assert list(iter_sentences(["One. Two. "])) == ["One.", "Two."]

    def test_matches_split_sentences_for_the_same_text(self):
        text = "Alpha. Beta! Gamma: delta; epsilon"
        assert list(iter_sentences([text])) == split_sentences(text)
