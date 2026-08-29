"""``python -m pdf_reader`` 入口，保持与 ``app.main`` 相同的 CLI/debug 语义。

导入本模块不解析 CLI、不启动服务器；``main`` 只在作为入口执行
（``python -m pdf_reader``）时运行。
"""

import sys

from pdf_reader.app import main

if __name__ == "__main__":
    sys.exit(main())
