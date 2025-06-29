import argparse
import json
import os
import shutil
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any
import traceback
from phoenix.otel import register
from openinference.instrumentation.smolagents import SmolagentsInstrumentor

import datasets
import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import login, snapshot_download
from scripts.extractor import extract_answer
from scripts.file_parse_tool import FileParseTool
from scripts.web_browser_tool import (
    ArchiveSearchTool,
    FinderTool,
    FindNextTool,
    PageDownTool,
    PageUpTool,
    SimpleTextBrowser,
    VisitPageTextTool,
)
from tqdm import tqdm
from scripts.search_tool import DuckDuckGoSearchTool
import logging
from smolagents import FinalAnswerTool
logging.basicConfig(level=logging.CRITICAL)
from smolagents import (
    CodeAgent,
    WebSearchTool,
    GoogleSearchTool,
    Model,
    ToolCallingAgent,
    OpenAIServerModel,
    PythonInterpreterTool,
    BASE_BUILTIN_MODULES
)

load_dotenv(override=True)
# login(os.getenv("HF_TOKEN"))
append_answer_lock = threading.Lock()

SERPAPI_API_KEY = "01b515185c2e7842665ca2086a5a04385672531fa8e22542392b3cc9c47dd659"
os.environ['SERPAPI_API_KEY'] = SERPAPI_API_KEY
# os.environ['SERPAPI_API_KEY'] = '01b515185c2e7842665ca2086a5a04385672531fa8e22542392b3cc9c47dd659'

tool_agent_steps=30
tool_agent_plan_interval=4

code_agent_step=12
code_agent_plan_interval=4
max_tokens=50000
extract_conv_num=5

search_engine="google" # duckduckgo
fileparser_max_tokens=100000

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--model_id", type=str, default="o4-mini")
    parser.add_argument("--run_name", type=str, default="gaia_o4-mini_search_4o_vqa")
    parser.add_argument("--split", type=str, default="validation")
    parser.add_argument("--use_open_models", type=bool, default=False)
    parser.add_argument("--use_raw_dataset", action="store_true")
    parser.add_argument("--extract_model_id", type=str, default="o4-mini")
    return parser.parse_args()

custom_role_conversions = {"tool-call": "assistant", "tool-response": "user"}

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"

BROWSER_CONFIG = {
    "viewport_size": 1024 * 5,
    "downloads_folder": "downloads",
    "request_kwargs": {
        "headers": {"User-Agent": user_agent},
        "timeout": 100,
    },
    # "serpapi_key": os.getenv("SERPAPI_API_KEY"),
    "serpapi_key": SERPAPI_API_KEY
}

os.makedirs(f"./{BROWSER_CONFIG['downloads_folder']}", exist_ok=True)


def create_agent_team(model: Model):
    text_limit = fileparser_max_tokens

    browser = SimpleTextBrowser(**BROWSER_CONFIG)
    # BASE_BUILTIN_MODULES.extend(["numpy", "pandas", "scipy", "librosa","pillow"])

    if search_engine=='google':
        websearch_tool=GoogleSearchTool(provider="serpapi")
    elif search_engine=='duckduckgo':
        websearch_tool=DuckDuckGoSearchTool()
    else:
        websearch_tool=WebSearchTool(engine="bing")
    WEB_TOOLS = [
        websearch_tool,
        # MyGoogleSearchTool(provider="serpapi", api_key=SERPAPI_API_KEY),
        # WebSearchTool(engine=search_engine),
        # DuckDuckGoSearchTool(),
        VisitPageTextTool(browser),
        PageUpTool(browser),
        PageDownTool(browser),
        FinderTool(browser),
        FindNextTool(browser),
        ArchiveSearchTool(browser),
        FileParseTool(text_limit),
        PythonInterpreterTool(BASE_BUILTIN_MODULES)        
    ]

    text_webbrowser_agent = ToolCallingAgent(
        model=model,
        tools=WEB_TOOLS,
        max_steps=tool_agent_steps,
        verbosity_level=2, # 日志输出复杂度
        planning_interval=tool_agent_plan_interval,
        name="search_agent",
        description="""A specialized team member responsible for searching the internet to gather information and answer your questions.
        Direct any inquiries that require up-to-date or web-based information to this agent.
        For best results, provide clear and detailed context, including relevant keywords, the desired timeframe, and any specific sources or websites if applicable.
        You may assign complex search tasks, such as comparing information between two webpages or summarizing recent developments on a topic.
        """,
        provide_run_summary=True,
    )
    text_webbrowser_agent.prompt_templates["managed_agent"]["task"] += """You can navigate to `.txt` files. If a non-html page is in another format, especially `.pdf` or a Youtube video, use tool 'file_parse_tool' to inspect it."""

    manager_agent = CodeAgent(
        model=model,
        tools=[FileParseTool(text_limit), PythonInterpreterTool(BASE_BUILTIN_MODULES)],
        max_steps=code_agent_step,
        verbosity_level=2, 
        additional_authorized_imports=["*"],
        planning_interval=code_agent_plan_interval,
        managed_agents=[text_webbrowser_agent],
    )
    return manager_agent


def load_gaia_dataset(use_raw_dataset: bool, split: str) -> datasets.Dataset:
    if not os.path.exists("data/gaia"):
        if use_raw_dataset:
            snapshot_download(
                repo_id="gaia-benchmark/GAIA",
                repo_type="dataset",
                local_dir="data/gaia",
                ignore_patterns=[".gitattributes", "README.md"],
            )
        else:
            snapshot_download(
                repo_id="smolagents/GAIA-annotated",
                repo_type="dataset",
                local_dir="data/gaia",
                ignore_patterns=[".gitattributes", "README.md"],
            )

    def preprocess_file_paths(row):
        if len(row["file_name"]) > 0:
            row["file_name"] = f"data/gaia/2023/{split}/" + row["file_name"]
        return row

    eval_ds = datasets.load_dataset(
        "data/gaia/GAIA.py",
        name="2023_all",
        split=split,
        trust_remote_code=True,
        data_files={"validation": "2023/validation/metadata.jsonl", "test": "2023/test/metadata.jsonl"},
        # data_files={"validation": "/Users/liyang.1236/Documents/python_project/gaia_agents/data/gaia/2023/validation/metadata_11_20.jsonl", "test": "2023/test/metadata.jsonl"},
    )

    eval_ds = eval_ds.rename_columns({"Question": "question", "Final answer": "true_answer", "Level": "level"})
    eval_ds = eval_ds.map(preprocess_file_paths)
    return eval_ds

def get_zip_description(file_path: str, question: str, file_parse_tool: FileParseTool):
    folder_path = file_path.replace(".zip", "")
    os.makedirs(folder_path, exist_ok=True)
    shutil.unpack_archive(file_path, folder_path)

    prompt_use_files = ""
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            prompt_use_files += "\n" + textwrap.indent(
                file_parse_tool(file_path, question),
                prefix="    ",
            )
    return prompt_use_files

def get_zip_files(file_path: str):
    folder_path = file_path.replace(".zip", "")
    os.makedirs(folder_path, exist_ok=True)
    shutil.unpack_archive(file_path, folder_path)
    file_paths=[]
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_paths.append(os.path.join(root, file))
    return file_paths

def append_answer(entry: dict, jsonl_file: str) -> None:
    jsonl_path = Path(jsonl_file)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with append_answer_lock, open(jsonl_file, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    assert jsonl_path.exists(), "File not found!"



def run_agent(
    example: dict, model_id: str, answers_file: str
) -> None:
    """
    Answers a single question with optimized, separate exception handling
    for agent execution and answer extraction, each with a retry mechanism.
    """

    model_params: dict[str, Any] = {
        "model_id": model_id,
        # "custom_role_conversions": custom_role_conversions,
    }
    if model_id == "o1":
        model_params["reasoning_effort"] = "high"
        model_params["max_completion_tokens"] = 50000
    else:
        model_params["max_tokens"] = max_tokens

    model = OpenAIServerModel(
        api_base="http://gpt-proxy.jd.com/gateway/common",
        api_key="64268e2b-188f-4e86-9b2a-8542ba3849c8",
        **model_params,
    )

    augmented_question = f"""As a professional problem-solving expert, I will ask you a question, please answer the following question with your full capabilities. You possess all the necessary tools and knowledge to solve this problem, so please utilize them fully.

    ## RULES:
    - Report your thoughts, and then finish your answer with the following template: FINAL ANSWER: [YOUR FINAL ANSWER].
    - Your FINAL ANSWER should be a number OR as few words as possible OR a comma separated list of numbers and/or strings.
    - If you are asked for a number, don't use comma to write your number neither use units such as $ or percent sign unless specified otherwise.
    - If you are asked for a string, don't use articles, neither abbreviations (e.g. for cities), and write the digits in plain text unless specified otherwise.
    - If you are asked for a comma separated list, apply the above rules depending of whether the element to be put in the list is a number or a string.

    ## NOTICE:
    1. Ensure accuracy and completeness in your answer.
    2. For numerical answers, make sure the units (e.g. per 1000, per million) and round precision (e.g. thousandths, two decimal places) match what's required in the problem.
    3. Use multiple tools and methods for solving and verification when necessary.
    4. Analyze the problem systematically to ensure no critical information is missed.
    5. If initial attempts are unsuccessful, try different approaches or methods.

    Remember, every question has a solution. Through rigorous thinking and appropriate use of tools, you will certainly find the correct answer.

    ## ORIGINAL QUESTION
    {example["question"]}

    """

    if example["file_name"]:
        if ".zip" in example["file_name"]:
            prompt_use_files = f"""## ATTACHED FILE PATHS:
    {str(get_zip_files(example['file_name']))}
            
    To answer this question, you should utilize the provided attached files. The file paths relevant to this task are listed above. You are allowed to use available tools to parse these files. If a certain file type cannot be parsed directly, you can generate and execute codes to extract the necessary information.
    """
        else:
            prompt_use_files = f"""## ATTACHED FILE PATH:
    {str(example['file_name'])}
            
    To answer this question, you should utilize the provided attached file. The file path relevant to this task are listed above. You are allowed to use available tools to parse this file. If the file cannot be parsed directly, you can generate and execute codes to extract the required information.
    """
        augmented_question += prompt_use_files

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=================================================================")
    print(f"{start_time} 开始任务: {example['task_id']}")
    print("=================================================================\n")

    max_attempts = 2

    output = None
    intermediate_steps = []
    parsing_error = False
    iteration_limit_exceeded = False
    final_exception = None    
    agent_memory = None

    agent = create_agent_team(model)

    for attempt in range(max_attempts):
        try:
            output=agent.run(augmented_question)
            agent_memory = agent.write_memory_to_messages()
            intermediate_steps = agent_memory              
            for memory_step in agent.memory.steps:
                memory_step.model_input_messages = None

            if output and "Agent stopped due to iteration limit or time limit." in str(output):
                iteration_limit_exceeded = True                     
            break
        except Exception as e:
            traceback.print_exc()
            final_exception = e
            if attempt == 0:
                print("\n============================================================================")
                print("An error occurred while executing `agent.run()`. Now restart the agent system")
                print("============================================================================\n")
                sleep(60)                
            else:
                print(f"Error: `agent.run()` still failed after {max_attempts} attempts.")

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n=================================================================")
    print(f"{end_time} 完成任务: {example['task_id']}")
    print("=================================================================\n")

    annotated_example = {
        "agent_name": model.model_id,
        "task_id": example["task_id"],   
        "prediction": None,     
        "true_answer": example["true_answer"],
        "level": example["level"],
        "question": example["question"],
        "augmented_question": augmented_question,
        "intermediate_steps": intermediate_steps,
        "parsing_error": None,
        "iteration_limit_exceeded": iteration_limit_exceeded,
        "agent_error": str(final_exception) if final_exception else None,
        "start_time": start_time,
        "end_time": end_time,
    }
    append_answer(annotated_example, answers_file)



def run_exract(target_path: dict, model_id: str="o4-mini", conv_num: int=5):
    """

    Args:
        target_path (dict): 
        model_id (str): 
        conv_num (int): 提取答案时所使用的对话轮次[-conv_num-3: -3]
    """
    model = OpenAIServerModel(
        api_base="http://gpt-proxy.jd.com/gateway/common",
        api_key="64268e2b-188f-4e86-9b2a-8542ba3849c8",
        max_tokens=50000,
        model_id=model_id,
        temperature=0.2,)

    file_path = Path(target_path)
    source_path = Path(file_path.parts[0], 'cache', *file_path.parts[1:])
    records=[]
    with open(source_path, "r", encoding="utf8") as file:
        for line in file:
            records.append(json.loads(line))
    tqdm.write("===========================================================")
    tqdm.write("-------------------- Extracted Resulst --------------------")
    tqdm.write("===========================================================\n")
    
    for record in tqdm(records):
        answer_attempt=0
        error_attempt=0
        final_result=None
        while True:
            try:
                final_result = extract_answer(
                    record['question'], 
                    record['intermediate_steps'],
                    model=model, 
                    conv_num=conv_num
                )
                record['prediction'] = final_result
                record['parsing_error'] = False

                if answer_attempt==0 and final_result == "Unable to determine": # 如果第一次没有明确答案则再次尝试
                    tqdm.write(f"Unable to parse {record['task_id']}, retry extraction again")
                    answer_attempt+=1
                    continue
                break
            except Exception as e:
                traceback.print_exc()
                if error_attempt == 0: # 如果第一次尝试出现错误
                    tqdm.write("\n===============================================================")
                    tqdm.write("An error occurred while executing `extract_answer`. Retrying...")
                    tqdm.write("===============================================================\n") 
                    error_attempt+=1
                    sleep(60)
                    continue                   
                else:
                    tqdm.write(f"Error: `extract_answer()` still failed after 2 attempts.")
                    record['prediction'] = None
                    record['parsing_error'] = str(e)
                break
        tqdm.write(f"task_id: {record['task_id']} > : {final_result}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            line = json.dumps(record, ensure_ascii=False)
            f.write(line + "\n")     
    print("\n\n答案保存到路径:", file_path.resolve(), "\n\n")


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


def main():
    args = parse_args()
    register(project_name=args.run_name)
    SmolagentsInstrumentor().instrument() 

    print("############## Task Args ################")
    print(f"Start run with arguments:\n {args}")
    print("tool_agent_steps: ",tool_agent_steps)
    print("tool_agent_plan_interval: ", tool_agent_plan_interval)
    print("code_agent_step: ", code_agent_step)
    print("code_agent_plan_interval: ", code_agent_plan_interval)
    print("max_tokens: ", max_tokens)
    print("extract_conv_num: ", extract_conv_num)
    print("##########################################")
    print("\n\n")

    eval_ds = load_gaia_dataset(args.use_raw_dataset, args.split)
    print("##########################################")
    print("Load evaluation dataset:")
    print(pd.DataFrame(eval_ds)["level"].value_counts())
    print("##########################################")
    print("\n\n")
    answers_file_path = f"output/{args.split}/{args.run_name}.jsonl"
    temp_answer_path = f"output/cache/{args.split}/{args.run_name}.jsonl"

    # exist_task_ids=[]
    # with open("output/top30/gaia_val_xsy_30_o4mini_0623_v1.jsonl", "r", encoding='utf-8') as file:
    #     for line in file:
    #         record=json.loads(line)
    #         exist_task_ids.append(record['task_id'])
    # tasks_to_run=[record for record in eval_ds.to_list() if record['task_id'] not in exist_task_ids]
    
    tasks_to_run=eval_ds.to_list()
    
    # tasks_to_run=[record for record in eval_ds.to_list() if record['task_id']=="bfcd99e1-0690-4b53-a85c-0174a8629083"]
    
    # eval_ds=eval_ds.shuffle()
    # tasks_to_run=[]
    # for record in eval_ds.to_list():
    #     if record['task_id'] not in ["6359a0b1-8f7b-499b-9336-840f9ab90688", "87c610df-bef7-4932-b950-1d83ef4e282b", "366e2f2b-8632-4ef2-81eb-bc3877489217"]:
    #         tasks_to_run.append(record)
    #     if len(tasks_to_run)==27:
    #         break

    # 并行执行
    with ThreadPoolExecutor(max_workers=args.concurrency) as exe:
        futures = [
            exe.submit(run_agent, example, args.model_id, temp_answer_path)
            for example in tasks_to_run
        ]
        for f in tqdm(as_completed(futures), total=len(tasks_to_run), desc="Processing tasks"):
            f.result()

    # 下面是循环串行执行的方法 
    # for example in tasks_to_run:
    #     answer_single_question(example, args.model_id, answers_file, FileParseTool(100000))

    run_exract(answers_file_path, args.extract_model_id, extract_conv_num)
    print("All tasks processed.")


if __name__ == "__main__":
    main()
    answers_file_path = f"output/validation/gaia_val_xsy_30_o4mini_0623_v2.jsonl"

    # run_exract(answers_file_path, "o4-mini", 5)