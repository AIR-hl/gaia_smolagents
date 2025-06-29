import json
import os
import shutil
import textwrap
from pathlib import Path
from pydub import AudioSegment
# import tqdm.asyncio
from smolagents.utils import AgentError
import speech_recognition as sr

from .file_parse_tool import FileParseTool

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
