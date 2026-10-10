## 新功能

- 新项目默认创建空白文档，无需准备已有 `.tex`；可用 `--template example` 选择原示例。
- 新增“新建文档”入口，创建前自动归档当前源文件和图片。
- 可在选中内容后插入段落、标题、公式、表格与图片。
- Windows 提供根目录 `start.bat`，再次启动会复用当前编辑器。
- 新建文档在 Windows 使用系统中文字体，修复本机 Fandol 字体显示缺失的问题。

## 下载与安装

- `visual_latex_editor-0.3.0-py3-none-any.whl`：Python 安装包，使用 `python -m pip install <文件名>` 安装。
- `visual_latex_editor-0.3.0-source.zip`：包含 Windows 启动脚本的源码包。
- 需要 Python 3.10+、Tectonic 和 Poppler。发布附件不含本机 Python 环境、编译器、个人图标或用户文档；安装步骤见 README。
- 新建时的旧文档归档位于项目的 `documents/<时间戳>/`，可通过 `--project` 重新打开。

## 验证

19 项单元与 HTTP 测试通过；原有真实编译集成检查通过；浏览器验证从零创建、插入五类内容、中文 PDF 预览与导出成功。
