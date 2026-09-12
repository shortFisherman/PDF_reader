"""Ship the MuPDF native library next to the ``pymupdf`` extension modules.

PyMuPDF 1.25 loads MuPDF through ``pymupdf/_mupdf`` (an extension module whose own
dependency chain finally needs ``mupdf.dll`` beside it on Windows).  The data policy
forbids shipping the wheel's C headers, so the development subtree is filtered out.
"""

from collections.abc import Iterable

from PyInstaller.utils.hooks import collect_dynamic_libs

DEVELOPMENT_DIRECTORY = "mupdf-devel"
DEVELOPMENT_SUFFIXES = (".lib", ".exp")


def _without_development_headers(toc: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop the wheel's C headers and import libraries from a ``collect_dynamic_libs`` TOC.

    ``collect_dynamic_libs`` yields ``(source, destination)`` pairs, where the destination keeps
    the library's directory inside the package (``pymupdf`` for ``mupdf.dll``).  Keeping that
    destination is what lets the frozen ``pymupdf._mupdf`` extension find MuPDF on Windows.
    """

    kept: list[tuple[str, str]] = []
    for source, destination in toc:
        normalized = f"{source}/{destination}".replace("\\", "/").lower()
        if f"/{DEVELOPMENT_DIRECTORY}/" in normalized or normalized.endswith(DEVELOPMENT_SUFFIXES):
            continue
        kept.append((source, destination))
    return kept


binaries = _without_development_headers(collect_dynamic_libs("pymupdf"))
