"""Vocab correction tests: known fixes apply, clean text is untouched."""

from speakspec import vocab

# Ordinary English with words adjacent to risky dictionary territory.
# The correction pass must leave every sentence byte-identical.
CLEAN_CORPUS = [
    "I went to see the doctor yesterday because my arm hurt.",
    "Jason said he would meet us at the gym after work.",
    "The crown jewels are kept under heavy guard in the tower.",
    "She wrote her thesis on Victorian literature and its critics.",
    "We watched the sequel last night; it was better than the original.",
    "My fast approach to cooking is mostly about preparation.",
    "The view from the cabin was spectacular in the morning light.",
    "He plays the bass in a small jazz band on weekends.",
    "Django Reinhardt's recordings influenced generations of guitarists.",
    "The web of alliances made the situation difficult to untangle.",
]


def test_known_corrections_apply() -> None:
    text = "I want to build it with fast api and sequel light, maybe deploy on fly io."
    corrected, applied = vocab.correct(text)
    assert "FastAPI" in corrected
    assert "SQLite" in corrected
    assert "Fly.io" in corrected
    assert len(applied) == 3


def test_longest_phrase_wins() -> None:
    corrected, _ = vocab.correct("store it as a jason web token")
    assert "JSON Web Token" in corrected
    assert "JSON web token" not in corrected


def test_case_insensitive_word_boundaries() -> None:
    corrected, _ = vocab.correct("We use Fast API and GRAPH QL heavily.")
    assert "FastAPI" in corrected
    assert "GraphQL" in corrected
    # No partial-word matches: "fasten" must not become "FastAPIen".
    corrected2, applied2 = vocab.correct("fasten your seatbelt")
    assert corrected2 == "fasten your seatbelt"
    assert applied2 == []


def test_clean_text_corpus_is_never_altered() -> None:
    for sentence in CLEAN_CORPUS:
        corrected, applied = vocab.correct(sentence)
        assert corrected == sentence, f"vocab pass altered clean text: {applied}"


def test_dictionary_has_at_least_50_entries() -> None:
    import json

    with vocab.vocab_file().open(encoding="utf-8") as fh:
        entries = json.load(fh)["corrections"]
    assert len(entries) >= 50, f"only {len(entries)} entries"
