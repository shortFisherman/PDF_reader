def test_debug_patches_imports_and_applies():
    from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
        AutomaticTermExtractor,
    )

    import debug_patches

    debug_patches.apply_patches()

    result = AutomaticTermExtractor.extract_terms_from_paragraphs
    assert callable(result)


def test_debug_patches_apply_patches_idempotent():
    """Twice calling apply_patches should not crash"""
    import debug_patches

    debug_patches.apply_patches()
    debug_patches.apply_patches()  # second call should not raise
