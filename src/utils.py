import importlib
import json
import os
from pathlib import Path
import re
import shutil

import datasets
import requests
from smolagents.agents import FinalAnswerPromptTemplate, ManagedAgentPromptTemplate, PlanningPromptTemplate, PromptTemplates
from smolagents.models import ChatMessage
import pandas as pd
import yaml
from os import path
from smolagents.utils import AgentError



def set_crawler_and_link_pool(crawler, link_pool):
    from src.tools import crawler_tool, download_tool, final_answer_tool, wikipedia_tool
    download_tool.set_link_pool(link_pool)
    wikipedia_tool.set_link_pool(link_pool)
    final_answer_tool.set_link_pool(link_pool)
    crawler_tool.set_crawler_and_link_pool(crawler, link_pool)


def load_prompt_from_yaml(file_path: str, key: str = "prompt") -> str | dict:
    try:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError(f"YAML 内容不是映射类型，解析结果：{type(data).__name__}")
        return data.get(key, "")
    except Exception as e:
        print(f"Error loading prompt from {file_path}: {e}")
        return ""
    

def load_prompt_template_from_yaml(file_path: str) -> PromptTemplates:
    prompt_template = PromptTemplates(
        system_prompt=load_prompt_from_yaml(file_path, "system_prompt"),
        planning=PlanningPromptTemplate(
            initial_plan=load_prompt_from_yaml(file_path, "planning")["initial_plan"],
            update_plan_pre_messages=load_prompt_from_yaml(file_path, "planning")["update_plan_pre_messages"],
            update_plan_post_messages=load_prompt_from_yaml(file_path, "planning")["update_plan_post_messages"],
        ),
        managed_agent=ManagedAgentPromptTemplate(task=load_prompt_from_yaml(file_path, "managed_agent")['task'], report=load_prompt_from_yaml(file_path, "managed_agent")['report']),
        final_answer=FinalAnswerPromptTemplate(pre_messages=load_prompt_from_yaml(file_path, "final_answer")["pre_messages"], post_messages=load_prompt_from_yaml(file_path, "final_answer")["post_messages"]),
    )
    return prompt_template

def load_gaia_dataset(data_path: str, split: str):
    def preprocess_file_paths(row):
        if len(row["file_name"]) > 0:
            row["file_name"] = f"data/gaia/2023/{split}/" + row["file_name"]
        return row

    eval_ds = datasets.load_dataset(
        path.join(data_path,"GAIA.py"),
        name="2023_all",
        split=split,
        trust_remote_code=True,
        data_files={"validation": "2023/validation/metadata.jsonl", "test": "2023/test/metadata.jsonl"},
        # data_files={"validation": "/Users/liyang.1236/Documents/python_project/gaia_agents/data/gaia/2023/validation/metadata_11_20.jsonl", "test": "2023/test/metadata.jsonl"},
    )

    eval_ds = eval_ds.rename_columns({"Question": "question", "Final answer": "true_answer", "Level": "level"})
    eval_ds = eval_ds.map(preprocess_file_paths)
    return eval_ds


def append_answer(entry: dict, jsonl_file: str, lock) -> None:
    jsonl_path = Path(jsonl_file)

    intermediate_steps = entry.get('intermediate_steps', [])
    if intermediate_steps:
        for i, step in enumerate(intermediate_steps):
            if isinstance(step, dict) and 'content' in step:
                step['content'] = step['content'][0]['text'] if isinstance(step['content'], list) else step['content']
            elif isinstance(step, ChatMessage):
                intermediate_steps[i] = {
                    "role": step.role.value,
                    "content": step.content[0]['text'],
                }
        entry['intermediate_steps'] = intermediate_steps
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with lock, open(jsonl_file, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    assert jsonl_path.exists(), "File not found!"


def serialize_agent_error(obj):
    if isinstance(obj, AgentError):
        return {"error_type": obj.__class__.__name__, "message": obj.message}
    else:
        return str(obj)


def get_tasks_to_run(data, total: int, base_filename: Path, tasks_ids: list[int]):
    f = base_filename.parent / f"{base_filename.stem}_answers.jsonl"
    done = set()
    if f.exists():
        with open(f, encoding="utf-8") as fh:
            done = {json.loads(line)["task_id"] for line in fh if line.strip()}

    tasks = []
    for i in range(total):
        task_id = int(data[i]["task_id"])
        if task_id not in done:
            if tasks_ids is not None:
                if task_id in tasks_ids:
                    tasks.append(data[i])
            else:
                tasks.append(data[i])
    return tasks

def get_zip_files(file_path: str):
    folder_path = file_path.replace(".zip", "")
    os.makedirs(folder_path, exist_ok=True)
    shutil.unpack_archive(file_path, folder_path)
    file_paths=[]
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_paths.append(os.path.join(root, file))
    return file_paths

def get_examples_to_answer(answers_file: str, eval_ds: datasets.Dataset) -> list[dict]:
    print(f"Loading answers from {answers_file}...")
    try:
        done_questions = pd.read_json(answers_file, lines=True)["question"].tolist()
        print(f"Found {len(done_questions)} previous results!")
    except Exception as e:
        print("Error when loading records: ", e)
        print("No usable records! Starting new.")
        done_questions = []
    return [line for line in eval_ds.to_list() if line["question"] not in done_questions]


import re

def clean_references(content: str) -> str:
    """
    删除 Markdown 文本中从 "References", "See also", "External links" 等
    常见结尾章节标题开始到文档末尾的所有内容。
    
    此版本使用 re.split()，方法健壮，能有效处理各种边缘情况。
    """
    if not content:
        return content

    # 构建关键词模式
    # 新增了 'see also', 'external links', '参见'
    keywords = r'references?|bibliography|citations?|sources?|参考文献|see also|external links|参见'

    # 将所有可能的标题模式组合成一个单一的、强大的正则表达式
    # 使用非捕获组 (?:...) 来组织模式
    # 每个模式的末尾都以 `.*` 结尾，以确保 re.split 会将整个标题行作为分隔符
    combined_pattern = re.compile(
        '|'.join([
            # 1. 标题格式: # References ...
            r"^\s*#{1,6}\s*(?:\*\*|\*|__|_)?(?:" + keywords + r")(?:\*\*|\*|__|_)?.*",
            # 2. 加粗/斜体格式: **References** ...
            r"^\s*(?:\*{1,2}|_{1,2})(?:" + keywords + r")(?:\*{1,2}|_{1,2}).*",
            # 3. 列表项格式: - References ...
            r"^\s*(?:[\-\*\+]|\d+\.)\s+(?:\*\*|\*|__|_)?(?:" + keywords + r")(?:\*\*|\*|__|_)?.*",
            # 4. 普通文本格式: References ...
            r"^\s*(?:" + keywords + r").*"
        ]),
        re.IGNORECASE | re.MULTILINE
    )

    parts = combined_pattern.split(content, maxsplit=1)

    if parts:
        return parts[0].rstrip()
    
    return content

def is_download_link(url: str, timeout: int = 30) -> bool:
    """
    Checks if a URL is a direct download link by inspecting HTTP headers.

    This function sends a HEAD request to efficiently get headers without
    downloading the full content.

    Returns:
        True if the link is determined to be a download link, False otherwise.
    """
    # Common non-webpage (downloadable) content types
    download_content_types = [
        'application/octet-stream', # Generic binary file
        'application/zip',
        'application/x-rar-compressed',
        'application/pdf',
        'application/msword',
        'application/postscript',
        'application/x-tex',
        'application/x-texinfo',
        'application/x-texinfo',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', # .xlsx
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', # .docx
        'image/', # Handle all image types
        'audio/', # Handle all audio types
        'video/', # Handle all video types
    ]

    try:
        # Use a HEAD request to get only headers, which is much faster.
        # allow_redirects=True ensures we check the final destination's headers.
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        headers = response.headers
        content_type = headers.get('Content-Type', '').lower()
        content_disposition = headers.get('Content-Disposition', '').lower()

        # 1. 'Content-Disposition: attachment' is a clear signal for download.
        if 'attachment' in content_disposition:
            return True

        # 2. Check if the Content-Type is for a typical file, not a webpage.
        if 'text/html' not in content_type and any(ct in content_type for ct in download_content_types):
            return True

    except requests.RequestException as e:
        # If the HEAD request fails, we can't be sure.
        # Log the error and assume it's not a download link to be safe.
        print(f"Could not check URL headers for {url}: {e}")
        return False

    # If checks don't indicate a download, assume it's a regular webpage.
    return False
