import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", CONFIG["deepseek"]["api_key"])
DEEPSEEK_MODEL = CONFIG["deepseek"]["model"]
DEEPSEEK_BASE_URL = CONFIG["deepseek"]["base_url"]
DPI = CONFIG["pdf_reader"]["dpi"]
CACHE_DIR = Path(CONFIG["pdf_reader"]["cache_dir"]).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG["translation"]["lang_in"]
TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
