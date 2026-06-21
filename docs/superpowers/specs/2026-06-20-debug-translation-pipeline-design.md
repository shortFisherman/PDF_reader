---
comet_change: debug-translation-pipeline
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-20-debug-translation-pipeline
status: final
---

# Debug Translation Pipeline — Technical Design

## 1. Architecture Overview

```
app.py --debug → config.DEBUG=True
  │
  └─ create_app()
       ├─ import debug_patches → patch AutomaticTermExtractor
       └─ import routes
            │
            └─ POST /api/translate/<page>
                 │
                 ├─ [trace] build_settings(debug=True)
                 │    └─ SettingsModel(basic=BasicSettings(debug=True))
                 │       → pdf2zh_next forces MAIN-PROCESS execution
                 │
                 ├─ [trace] submit translate page N
                 │
                 ├─ do_translate_async_stream()
                 │    │
                 │    └─ babeldoc pipeline (in-process)
                 │         └─ AutomaticTermExtractor (PATCHED)
                 │              → logs per-batch LLM interaction
                 │
                 ├─ [trace] merge glossary
                 ├─ [trace] replace page N
                 └─ [trace] done (elapsed Xs)
```

## 2. Component Design

### 2.1 debug_patches.py

New module. Contains a single public function `apply_patches()` called at import time.

```python
# Pseudocode
def apply_patches():
    from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
        AutomaticTermExtractor,
    )
    _original = AutomaticTermExtractor.extract_terms_from_paragraphs

    def _patched(self, paragraphs, pbar=None, paragraph_token_count=0):
        trace = logging.getLogger("pdf_reader.debug_trace")
        # Log batch input
        n_inputs = len([p for p in paragraphs.paragraphs if p.unicode])
        total_chars = sum(len(p.unicode) for p in paragraphs.paragraphs if p.unicode)
        trace.info("Term batch: %d paragraphs, %d chars", n_inputs, total_chars)

        # Call original
        try:
            _original(self, paragraphs, pbar, paragraph_token_count)
        except Exception:
            trace.warning("Term extraction batch failed", exc_info=True)

    AutomaticTermExtractor.extract_terms_from_paragraphs = _patched
```

**Patch target**: Instead of wrapping `extract_terms_from_paragraphs` (which is complex to re-implement), patch lower-level methods:

1. **Patch `_process_llm_response`** (line 193): Already handles logging for parse errors
2. **Better approach: Patch the LLM call site** — intercept `self.translate_engine.llm_translate()` return value

The cleanest approach: patch after `output = self.translate_engine.llm_translate(...)` inside `extract_terms_from_paragraphs`. Since we wrap the entire method, we call the original, then log based on what happened.

Actually, given the method's complexity, a simpler approach: **wrap just the llm_translate call** by monkey-patching `BaseTranslator.llm_translate` on the `translate_engine` instance. But we don't have access to the instance at patch time.

**Recommended**: Wrap the entire `extract_terms_from_paragraphs` with a decorator that intercepts calls to `self.translate_engine.llm_translate` and logs before/after.

Simpler approach: **Monkey-patch at the `self.shared_context.add_raw_extracted_term_pair` level** to count terms. And patch the `logger.warning` at line 352 to also log the LLM response.

Actually, the SIMPLEST reliable approach: patch `self.translate_engine.llm_translate` globally on the translate engine class:

```python
_original_llm = BaseTranslator.llm_translate

def _patched_llm_translate(self, prompt, **kwargs):
    is_term = kwargs.get("rate_limit_params", {}).get("request_json_mode", False)
    trace = logging.getLogger("pdf_reader.debug_trace")
    if is_term:
        trace.info("Term extraction LLM call: prompt=%d chars", len(prompt))
    result = _original_llm(self, prompt, **kwargs)
    if is_term:
        trace.info("Term extraction LLM response: %d chars", len(result))
        trace.info("Term extraction LLM raw (500): %s", result[:500])
    return result

BaseTranslator.llm_translate = _patched_llm_translate
```

This is simple, robust, and intercepts every LLM call. The `request_json_mode` flag in `rate_limit_params` distinguishes term extraction calls from translation calls.

But wait, the `llm_translate` might not exist directly on the BaseTranslator. Let me check...

Actually, the requirement says "request_json_mode" is passed as `rate_limit_params` (automatic_term_extractor.py:329-332). The base translator may handle this differently based on the implementation.

Let me use a different approach: instead of patching `llm_translate`, we wrap `extract_terms_from_paragraphs` but ONLY add logging around the critical section (lines 327-349 in the original). We save the original method, and in the patched version:
1. Do everything the original does but with logging added
2. After line 333 (llm_translate returns), log the response
3. After line 348 (loop done), log the term count

This requires duplicating the method body. That's fragile.

**Best approach**: Wrap the original, but use `inspect` or a context manager to capture the output. Actually, the simplest: use `unittest.mock.patch` or write a simple wrapper:

```python
original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs

def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
    trace = logging.getLogger("pdf_reader.debug_trace")
    n_paras = len(paragraphs.paragraphs)
    chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
    trace.info("Term batch start: %d paragraphs, %d chars", n_paras, chars)
    
    # Count terms before
    terms_before = len(self.shared_context.raw_extracted_terms)
    
    try:
        return original_extract(self, paragraphs, pbar, paragraph_token_count)
    finally:
        terms_after = len(self.shared_context.raw_extracted_terms)
        trace.info("Term batch end: extracted %d new terms", terms_after - terms_before)
```

This is clean, minimal, and doesn't duplicate code. The only thing missing is the actual LLM response content. But since the response is not stored (it's processed inline), we can't log it from outside the method.

Hmm, but the user really wants to see the LLM response. Let me think...

Actually, we CAN get the response! The `tracker.set_output(output)` at line 334 stores the output. And the tracker is part of the `BatchParagraph` object. If we set debug=True, the tracking JSON is saved to working_dir. But working_dir gets cleaned.

Alternative: We can also set `translation_config.working_dir` to a persistent directory AND patch `cleanup_temp_files` to NOT delete it. But that's getting complex.

SIMPLEST solution: Patch `_clean_json_output` to log the raw output BEFORE cleaning. OR: patch `json.loads` call site.

Actually, let me reconsider. The cleanest, most maintainable approach is:

1. Patch at the class level (`AutomaticTermExtractor.extract_terms_from_paragraphs`) but only ADD logging around the original call
2. Log: batch size before, term count delta after
3. For the LLM response content, we can access it indirectly: the response is stored in `tracker.output` (line 334), and tracker is in `paragraphs.tracker`. We read it after the original method completes.

Wait, the tracker is set INSIDE the original method. So after the original returns, we can read `paragraphs.tracker.output` and `paragraphs.tracker.input`.

Let me revise the design:

```python
def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
    trace = logging.getLogger("pdf_reader.debug_trace")
    n_paras = len(paragraphs.paragraphs)
    chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
    trace.info("Term batch: %d paragraphs, %d chars", n_paras, chars)
    
    terms_before = len(self.shared_context.raw_extracted_terms)
    
    try:
        return original_extract(self, paragraphs, pbar, paragraph_token_count)
    finally:
        terms_after = len(self.shared_context.raw_extracted_terms)
        trace.info("Term batch done: extracted %d terms", terms_after - terms_before)
        
        # Log LLM response from tracker
        tracker = paragraphs.tracker
        llm_input = getattr(tracker, "input", "")
        llm_output = getattr(tracker, "output", "")
        if llm_output:
            trace.info("Term batch prompt: %d chars", len(llm_input))
            trace.info("Term batch response: %d chars", len(llm_output))
            trace.info("Term batch raw (500 chars): %s", llm_output[:500])
```

This is clean! The tracker.input and tracker.output are set by the original method before our finally block runs. So we can always read them.

Let me use this approach for the Design Doc.

### 2.2 services.py changes

Add `debug: bool = False` parameter to `build_settings()`. When True, create `BasicSettings(debug=True)` and pass to `SettingsModel`.

```python
def build_settings(..., debug: bool = False):
    ...
    return SettingsModel(
        basic=BasicSettings(debug=debug),
        ...
    )
```

### 2.3 config.py changes

Add `DEBUG: bool = False` default.

### 2.4 app.py changes

Add `--debug` argument parsing:
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args, _ = parser.parse_known_args()
    if args.debug:
        config.DEBUG = True
```

### 2.5 routes.py changes

Add step logging around the translation flow. When debug mode is active, log before/after each step with elapsed time.

### 2.6 Debug trace log file

In routes.py, when setting up the translation, create a file handler that writes to `cache/<pdf_hash>/debug_trace.log`:
```python
if config.DEBUG and cumulative_glossary_path:
    trace_logger = logging.getLogger("pdf_reader.debug_trace")
    fh = logging.FileHandler(str(cumulative_glossary_path / "debug_trace.log"))
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
    trace_logger.addHandler(fh)
```

## 3. Key Decisions

| Decision | Rationale |
|----------|-----------|
| debug=True forces main process | REQUIRED for monkey-patch to take effect (subprocess won't inherit patches) |
| Patch class-level method, read tracker after | Clean: no code duplication, gets LLM response from tracker.input/output attributes |
| Console + file dual output | Real-time visibility + post-mortem analysis |
| No custom working_dir | Avoids babeldoc cleanup race; debug byproducts are auto-cleaned |
| `--debug` CLI flag rather than config.toml | Explicit user intent, no config file modification needed |

## 4. Error Handling

- ImportError when loading babeldoc symbols for patching → log warning, skip patch, continue normally
- Patch function raises exception → caught by finally in routes.py, logged
- File handler creation fails (permission, disk full) → log warning, continue with console-only trace

## 5. Testing

- Manual: `python app.py --debug` → translate page → verify console output + `cache/<hash>/debug_trace.log`
- Manual: `python app.py` (no flag) → verify no extra output
- Auto: `pytest tests/ -q` → 39 tests unchanged
- Lint: `ruff check` → clean
