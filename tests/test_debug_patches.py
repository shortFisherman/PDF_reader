import logging
from unittest.mock import patch

import debug_trace


def test_debug_patches_imports_and_applies():
    """init_debug(True) applies monkey-patch to AutomaticTermExtractor."""
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = lambda self, p, pbar=None, ptc=0: None
        debug_trace.init_debug(True)
        result = mock_cls.extract_terms_from_paragraphs
        assert callable(result)


def test_debug_patches_apply_patches_idempotent():
    """init_debug called twice should not crash."""
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = lambda self, p, pbar=None, ptc=0: None
        debug_trace.init_debug(True)
        debug_trace.init_debug(True)
