import tempfile
from pathlib import Path

import pymupdf
import pytest

from services import build_settings, render_page, sha256


def test_sha256_consistent():
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp.write(b"hello world")
    tmp.close()
    h1 = sha256(tmp.name)
    h2 = sha256(tmp.name)
    assert h1 == h2
    assert len(h1) == 64
    Path(tmp.name).unlink()

def test_sha256_different():
    tmp1 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp1.write(b"hello")
    tmp1.close()
    tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp2.write(b"world")
    tmp2.close()
    assert sha256(tmp1.name) != sha256(tmp2.name)
    Path(tmp1.name).unlink()
    Path(tmp2.name).unlink()

def test_render_page_valid(sample_pdf):
    doc = pymupdf.open(str(sample_pdf))
    data = render_page(doc, 0, 72)
    assert isinstance(data, bytes)
    assert len(data) > 0
    doc.close()

def test_render_page_out_of_range(sample_pdf):
    doc = pymupdf.open(str(sample_pdf))
    with pytest.raises(ValueError, match="page out of range"):
        render_page(doc, 999, 72)
    doc.close()

def test_build_settings_basic():
    settings = build_settings("dummy.pdf")
    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True

def test_build_settings_with_prompt():
    settings = build_settings("dummy.pdf", "translate waveguide as 波导")
    assert settings.translation.custom_system_prompt == "translate waveguide as 波导"

def test_build_settings_with_output_dir():
    settings = build_settings("dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"

def test_build_settings_without_output_dir():
    settings = build_settings("dummy.pdf")
    assert getattr(settings.translation, "output", None) is None
