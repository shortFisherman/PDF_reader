"""``python -m pdf_reader`` 入口，保持与 ``app.main`` 相同的 CLI/debug 语义。"""

import sys

from pdf_reader.app import main

sys.exit(main())
