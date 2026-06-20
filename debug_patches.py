import logging

from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
    AutomaticTermExtractor,
)

logger = logging.getLogger("pdf_reader.debug_trace")

_original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs


def apply_patches() -> None:
    def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
        n_paras = len(paragraphs.paragraphs)
        chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
        logger.info("Term batch: %d paragraphs, %d chars", n_paras, chars)

        terms_before = len(self.shared_context.raw_extracted_terms)

        result = _original_extract(self, paragraphs, pbar, paragraph_token_count)

        terms_after = len(self.shared_context.raw_extracted_terms)
        logger.info("Term batch done: extracted %d terms", terms_after - terms_before)

        tracker = paragraphs.tracker
        llm_input = getattr(tracker, "input", "")
        llm_output = getattr(tracker, "output", "")
        if llm_output:
            logger.info("Term batch prompt: %d chars", len(llm_input))
            logger.info("Term batch response: %d chars", len(llm_output))
            logger.info("Term batch raw (500 chars): %s", llm_output[:500])
        elif not llm_input and terms_after == terms_before:
            logger.info("Term batch: no LLM call made (empty inputs)")

        return result

    AutomaticTermExtractor.extract_terms_from_paragraphs = patched_extract
