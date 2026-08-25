"""Joining biomarkers to tumours across two independent LLM passes.

Measured on TCGA-BH-A18H: the tumour pass produced "Right breast, 9 o'clock"
and the biomarker pass "Part 1: Right breast, 9 o'clock". An exact-string join
matched nothing, which would have rendered two tumours with no biomarkers.
"""

import pytest

from app.pipelines.biomarker_extractor import _resolve_label

KNOWN = ["Right breast, 9 o'clock", "Left breast, 12 o'clock"]


class TestResolveLabel:
    def test_exact_match(self):
        assert _resolve_label("Right breast, 9 o'clock", KNOWN) == KNOWN[0]

    def test_case_and_whitespace_insensitive(self):
        assert _resolve_label("  RIGHT BREAST,   9 O'CLOCK ", KNOWN) == KNOWN[0]

    def test_prefixed_label_resolves(self):
        """The actual observed mismatch."""
        assert _resolve_label("Part 1: Right breast, 9 o'clock", KNOWN) == KNOWN[0]
        assert _resolve_label("Part 3: Left breast, 12 o'clock", KNOWN) == KNOWN[1]

    def test_shorter_label_resolves(self):
        assert _resolve_label("Left breast", ["Left breast, 12 o'clock"]) == (
            "Left breast, 12 o'clock"
        )

    def test_unrelated_label_is_dropped(self):
        """Better unattributed than attributed to the wrong breast."""
        assert _resolve_label("Axillary lymph node", KNOWN) is None

    def test_ambiguous_match_is_dropped(self):
        """Two candidates means we cannot tell — do not guess."""
        known = ["breast", "breast, left"]
        assert _resolve_label("breast, left upper", known) is None

    def test_none_label_passes_through(self):
        assert _resolve_label(None, KNOWN) is None

    def test_no_vocabulary_leaves_label_untouched(self):
        """Single-tumour reports pass no vocabulary; the label must survive."""
        assert _resolve_label("Whatever the model said", []) == "Whatever the model said"


class TestVocabularyPrompt:
    def test_labels_render_into_the_prompt(self):
        from app.pipelines.biomarker_extractor import LABEL_VOCABULARY_PROMPT

        rendered = LABEL_VOCABULARY_PROMPT.format(
            labels="\n".join(f"  - {l}" for l in KNOWN)
        )
        assert "Right breast, 9 o'clock" in rendered
        assert "Left breast, 12 o'clock" in rendered
        assert "VERBATIM" in rendered

    def test_prompt_instructs_null_over_guessing(self):
        from app.pipelines.biomarker_extractor import LABEL_VOCABULARY_PROMPT

        assert "null" in LABEL_VOCABULARY_PROMPT
        assert "rather than guessing" in LABEL_VOCABULARY_PROMPT
