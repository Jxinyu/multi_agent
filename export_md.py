import os
import argparse
import sys


def is_text_file(file_path):
    """
    简单的检查文件是否为文本文件的方法。
    """
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\x00' in chunk:
                return False
            return True
    except Exception:
        return False


def project_to_markdown(source_dir, output_file,
                        excluded_dirs=None,
                        excluded_exts=None,
                        excluded_filenames=None,
                        specific_ignore_dirs=None,  # 新增：接收特定目录集合
                        specific_ignore_files=None):  # 新增：接收特定文件集合
    """
    将项目目录下的所有代码文件导出到一个 Markdown 文件中。
    """
    # 1. 初始化集合
    excluded_dirs = set(excluded_dirs) if excluded_dirs else set()
    excluded_exts = set(excluded_exts) if excluded_exts else set()
    excluded_filenames = set(excluded_filenames) if excluded_filenames else set()

    # 2. 路径标准化处理 (确保 Windows/Mac 路径分隔符一致)
    #    这样你在配置里写 "src/logs" 也能在 Windows 上匹配 "src\logs"
    specific_ignore_dirs = {os.path.normpath(p) for p in (specific_ignore_dirs or [])}
    specific_ignore_files = {os.path.normpath(p) for p in (specific_ignore_files or [])}

    # 转换为绝对路径
    source_dir = os.path.abspath(source_dir)
    current_script_path = os.path.abspath(__file__)
    output_file_abs = os.path.abspath(output_file)

    file_count = 0

    with open(output_file, 'w', encoding='utf-8') as md_file:
        md_file.write(f"# Project Export: {os.path.basename(source_dir)}\n\n")
        md_file.write(f"**Source Directory:** `{source_dir}`\n\n")
        md_file.write("---\n\n")

        for root, dirs, files in os.walk(source_dir):

            # --- 目录过滤逻辑 (核心修改) ---
            # 我们需要原地修改 dirs 列表，以阻止 os.walk 进入这些目录
            valid_dirs = []
            for d in dirs:
                # A. 检查目录名是否在通用排除列表中 (如 node_modules)
                if d in excluded_dirs or d.startswith('.'):
                    continue

                # B. 检查特定的相对路径是否被排除 (如 src/logs)
                full_dir_path = os.path.join(root, d)
                rel_dir_path = os.path.relpath(full_dir_path, source_dir)

                if rel_dir_path in specific_ignore_dirs:
                    print(f"[-] 跳过特定目录: {rel_dir_path}")
                    continue

                valid_dirs.append(d)

            # 应用过滤结果
            dirs[:] = valid_dirs

            # --- 文件遍历 ---
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, source_dir)
                _, ext = os.path.splitext(file)

                # --- 文件过滤逻辑开始 ---

                # 1. 排除特定全名的文件 (如 .env)
                if file in excluded_filenames:
                    continue

                # 2. 排除特定的文件扩展名
                if ext.lower() in excluded_exts:
                    continue

                # 3. 新增：排除特定的文件路径 (如 config/keys.py)
                if relative_path in specific_ignore_files:
                    print(f"[-] 跳过特定文件: {relative_path}")
                    continue

                # 4. 排除输出文件本身 & 排除脚本自身
                file_abs = os.path.abspath(file_path)
                if file_abs == output_file_abs or file_abs == current_script_path:
                    continue

                # --- 文件过滤逻辑结束 ---

                # 5. 检查是否为文本文件
                if not is_text_file(file_path):
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        md_file.write(f"## File: `{relative_path}`\n\n")
                        lang = ext[1:] if ext else ""
                        md_file.write(f"```{lang}\n")
                        md_file.write(content)
                        if not content.endswith('\n'):
                            md_file.write('\n')
                        md_file.write("```\n\n")

                        print(f"[+] 已导出: {relative_path}")
                        file_count += 1

                except Exception as e:
                    print(f"[-] 读取失败: {relative_path}, 错误: {e}")

    print(f"\n>>> 完成！共导出 {file_count} 个文件。")
    print(f">>> 输出文件: {output_file_abs}")


if __name__ == "__main__":
    # ================= 配置区域 =================

    # 1. 通用排除目录 (只要目录名匹配就排除，不管在哪一层)
    DEFAULT_EXCLUDE_DIRS = {
        "__pycache__", "node_modules", ".git", ".idea", ".vscode",
        "daily_memory_exports", "token", "data",
        "venv", "env", "build", "dist", "target", "migrations",
        "result_data", "chroma_db", "examples"
    }

    # 2. 通用排除扩展名
    DEFAULT_EXCLUDE_EXTS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".json", ".mermaid",
        ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so", ".dylib",
        ".zip", ".tar", ".gz", ".7z", ".rar", ".sqlite3", ".md",
        ".db", ".sqlite", ".pdf", ".docx", ".log"
    }

    # 3. 通用排除文件名 (精确匹配文件名)
    DEFAULT_EXCLUDE_FILENAMES = {
        ".env", ".gitignore", "LICENSE", "package-lock.json", ".DS_Store",
        "yarn.lock", "go.sum", "pnpm-lock.yaml", 'private_key', 'public_key', 'metadata设计.md', 'export_md.py',
        'langgraph.json', 'nzqa_institutions_full.csv', 'test.py', '任务.md', '智能体机构.svg'
    }

    # ------------------ 新增功能 ------------------

    # 4. 特定目录排除 (填写相对于项目根目录的路径)
    # 示例: {"src/logs", "backend/tests/temp"}
    DEFAULT_SPECIFIC_IGNORE_DIRS = {
        ".langgraph_api",
        "algorithm",
        "chain_graph",
        "config",
        "data",
        "document",
        "multi_domain_enterprise_project/rag/data",
        # "experiment/仿真社会评估/宏观行为验证/data",
        # "experiment/仿真社会评估/宏观行为验证/output",
        # "experiment/仿真社会评估/微观行为验证",
        # "experiment/仿真社会评估/内部一致性验证/data",
        # "experiment/仿真社会评估/内部一致性验证/output",
        # "experiment/仿真社会评估/案例验证/data",
        # "experiment/仿真社会评估/案例验证/output",
        # "experiment/仿真社会评估/验证通过",
        # "experiment/低粒度模型筛选有效性验证/验证通过",
        # "experiment/低粒度模型筛选有效性验证/data",
        # "experiment/多粒度方法评估/效率实验/data",
        # "experiment/多粒度方法评估/效率实验/output",
        # "experiment/多粒度方法评估/效率实验/验证通过",
        # "experiment/多粒度方法评估/机制敏感度实验/data",
        # "experiment/多粒度方法评估/机制敏感度实验/output",
        # "experiment/多粒度方法评估/机制敏感度实验/验证通过",
        # "experiment/多粒度方法评估/闭环有效性实验/data",
        # "experiment/多粒度方法评估/闭环有效性实验/output",
        # "experiment/多粒度方法评估/闭环有效性实验/验证通过",

        # "method/",
        # "config/",
        # "nsga/",
        # "utils/",

        "method/store/chroma_db",
        "method/store/daily_memory_exports",
        "method/store/token",
        "result_data",
    }

    # 5. 特定文件排除 (填写相对于项目根目录的路径)
    # 示例: {"config/secret.py", "scripts/legacy.py"}
    DEFAULT_SPECIFIC_IGNORE_FILES = {
        "project_code.md",  # 示例
        "inquiry_cost.py",  # 示例
        "other.txt",  # 示例
        "experiment/仿真社会评估/微观行为验证/评估标准.md",  # 示例
    }

    # ===========================================

    parser = argparse.ArgumentParser(description="将项目代码导出为 Markdown 文档")
    parser.add_argument("path", nargs="?", default=".", help="项目根目录路径")
    parser.add_argument("-o", "--out", default="project_code.md", help="输出文件名")

    args = parser.parse_args()

    # 自动将当前脚本名加入排除列表
    current_script_name = os.path.basename(__file__)
    DEFAULT_EXCLUDE_FILENAMES.add(current_script_name)

    project_to_markdown(
        source_dir=args.path,
        output_file=args.out,
        excluded_dirs=DEFAULT_EXCLUDE_DIRS,
        excluded_exts=DEFAULT_EXCLUDE_EXTS,
        excluded_filenames=DEFAULT_EXCLUDE_FILENAMES,
        # 传入新增的配置变量
        specific_ignore_dirs=DEFAULT_SPECIFIC_IGNORE_DIRS,
        specific_ignore_files=DEFAULT_SPECIFIC_IGNORE_FILES
    )
