"""Collect the ``tiktoken_ext`` encoding plugins that tiktoken finds at run time.

``tiktoken.registry`` calls ``pkgutil.iter_modules(tiktoken_ext.__path__)`` and then
imports whatever it finds, so no static import statement mentions
``tiktoken_ext.openai_public``.  Without this hook the frozen service would fail on the
first encoding lookup even though every import in the source tree resolves.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("tiktoken_ext")
