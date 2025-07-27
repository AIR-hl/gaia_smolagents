import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import sleep
import traceback
from openinference.instrumentation import using_metadata
from phoenix.otel import register
from openinference.instrumentation.smolagents import SmolagentsInstrumentor
import pkgutil
from dotenv import load_dotenv
from src.extractor import run_extract
from src.tools.arxiv_tool import ArxivWebSearchTool
from src.tools.search_tool import IntegratedSearchTool
from src.tools.text_tool import text_parse_tool
from src.tools.pdf_tool_v2 import PDFParseTool
from src.tools.image_tool import image_parse_tool
from src.tools.ocr_tool import ocr_tool
from src.tools.audio_tool import audio_parse_tool
from src.tools.doc_tool import doc_parse_tool
from src.tools.html_tool import html_parse_tool
from src.tools.scientific_tool import pdb_parse_tool
from src.tools.final_answer_tool import final_answer
from src.tools.download_tool import download_file
from src.tools.github_tool import GitHubRepoSearchTool, GitHubIssueSearchTool, GitHubPullRequestSearchTool, GitHubReleaseSearchTool
from src.tools.crawler_tool import CrawlWebpageTool, CrawlerArchiveWebpageTool, SimpleCrawler, LinkPool
from src.tools.youtube_tool import visit_ytb_page, get_ytb_screenshot, get_ytb_subtitle, get_ytb_audio
from src.utils import load_gaia_dataset, append_answer, get_zip_files, load_prompt_from_yaml, load_prompt_template_from_yaml, set_crawler_and_link_pool
from src.tools.wikipedia_tool import WikiSearchTool, WikiPageTool
from tqdm import tqdm
from rich.console import Console
from smolagents.agents import CodeAgent
from smolagents.models import OpenAIServerModel
from smolagents import PythonInterpreterTool, BASE_BUILTIN_MODULES
from smolagents.local_python_executor import LocalPythonExecutor
from smolagents.monitoring import AgentLogger, LogLevel

load_dotenv(override=True)

append_answer_lock = threading.Lock()

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--model_id", type=str, default="o4-mini")
    parser.add_argument("--extract_model_id", type=str, default="o4-mini")    
    parser.add_argument("--run_name", type=str, default="gaia_run")
    parser.add_argument("--split", type=str, default="validation")
    parser.add_argument("--use_phoenix", action="store_true", default=False)
    return parser.parse_args()

os.environ['SERPAPI_API_KEY'] = os.getenv("SERPAPI_API_KEY", "")
os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")
os.environ["GITHUB_API_TOKEN"] = os.getenv("GITHUB_API_TOKEN", "")

search_agent_steps = 60
search_agent_plan_interval = 4
code_agent_step = 60
code_agent_plan_interval = 4
manager_agent_step = 80
manager_agent_plan_interval = 5
max_tokens = 200000
extract_conv_num = 5
SEARCH_ENGINE = ["google"]
search_tool_func = IntegratedSearchTool(SEARCH_ENGINE, num0=8)

ALL_SEARCH_TOOLS = [
    search_tool_func,
    WikiSearchTool(),
    ArxivWebSearchTool(),
    GitHubRepoSearchTool(),
    GitHubIssueSearchTool(),
    GitHubPullRequestSearchTool(),
    GitHubReleaseSearchTool(),
]

ALL_PARSING_TOOLS = [
    PDFParseTool(),
    doc_parse_tool,
    image_parse_tool,
    ocr_tool,
    text_parse_tool,
    audio_parse_tool,
    html_parse_tool,
    pdb_parse_tool,
]

WEB_TOOLS = [
    CrawlWebpageTool(),
    WikiPageTool(),
    download_file,
    CrawlerArchiveWebpageTool(),
    visit_ytb_page,
    get_ytb_subtitle,
    get_ytb_screenshot,
    get_ytb_audio,
    final_answer,
]

def create_agent_team(project_root: Path, logger=None, **kwargs):
    link_pool = LinkPool()
    crawler = SimpleCrawler(link_pool=link_pool)
    set_crawler_and_link_pool(crawler, link_pool)

    for module in pkgutil.iter_modules():
        BASE_BUILTIN_MODULES.append(module.name)
        BASE_BUILTIN_MODULES.append(f"{module.name}.*")

    search_agent_description = "An expert in web retrieval and information gathering..."
    code_agent_description = "An expert in programming, logical reasoning, and math..."

    search_agent = CodeAgent(
        model=kwargs['search_model'],
        tools=[*ALL_SEARCH_TOOLS, *WEB_TOOLS, *ALL_PARSING_TOOLS],
        max_steps=search_agent_steps,
        verbosity_level=2,
        planning_interval=search_agent_plan_interval,
        name="Retrieval_Expert",
        description=search_agent_description,
        provide_run_summary=False,
        prompt_templates=load_prompt_template_from_yaml(project_root / "prompts/search_agent/code_agent.yaml"),
        logger=logger or AgentLogger(level=LogLevel.INFO),
    )
    if isinstance(search_agent.python_executor, LocalPythonExecutor):
        search_agent.python_executor.static_tools = {"open": open}

    code_agent = CodeAgent(
        model=kwargs['code_model'],
        tools=[*ALL_PARSING_TOOLS, *WEB_TOOLS, PythonInterpreterTool(BASE_BUILTIN_MODULES)],
        max_steps=code_agent_step,
        verbosity_level=2,
        additional_authorized_imports=["*"],
        planning_interval=code_agent_plan_interval,
        provide_run_summary=True,
        name="Logic_Expert",
        description=code_agent_description,
        prompt_templates=load_prompt_template_from_yaml(project_root / "prompts/logic_agent/code_agent.yaml"),
        logger=logger or AgentLogger(level=LogLevel.INFO),
    )
    if isinstance(code_agent.python_executor, LocalPythonExecutor):
        code_agent.python_executor.static_tools = {"open": open}

    manager_agent = CodeAgent(
        model=kwargs['manager_model'],
        tools=[*ALL_PARSING_TOOLS, PythonInterpreterTool(BASE_BUILTIN_MODULES)],
        max_steps=manager_agent_step,
        verbosity_level=2,
        planning_interval=manager_agent_plan_interval,
        managed_agents=[search_agent, code_agent],
        prompt_templates=load_prompt_template_from_yaml(project_root / "prompts/manage_agent/code_agent.yaml"),
        logger=logger or AgentLogger(level=LogLevel.INFO),
    )
    if isinstance(manager_agent.python_executor, LocalPythonExecutor):
        manager_agent.python_executor.static_tools = {"open": open}
    return manager_agent

def run_agent(example: dict, run_name: str, answers_file: str, project_root: Path) -> None:
    task_id = example["task_id"]
    workspace_path = project_root / "workspaces" / run_name / task_id
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    original_cwd = os.getcwd()
    os.chdir(workspace_path)

    try:
        log_dir = project_root / f"log/{run_name}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = log_dir / f"{task_id}.log"

        if example.get("file_name") and not os.path.isabs(example["file_name"]):
            example["file_name"] = str(project_root / example["file_name"])

        with open(log_file_path, "w", encoding="utf-8") as log_file:
            console = Console(file=log_file, record=False, force_terminal=False)
            agent_logger = AgentLogger(level=LogLevel.INFO, console=console)

            manager_model = OpenAIServerModel(model_id="anthropic.claude-sonnet-4-20250514-v1:0", api_base=os.getenv("OPENAI_BASE_URL"), api_key=os.getenv("OPENAI_API_KEY"), max_tokens=65535, timeout=100, client_kwargs={"max_retries": 3})
            search_model = OpenAIServerModel(model_id="anthropic.claude-sonnet-4-20250514-v1:0", api_base=os.getenv("OPENAI_BASE_URL"), api_key=os.getenv("OPENAI_API_KEY"), max_tokens=65535, timeout=100, temperature=0.4, client_kwargs={"max_retries": 3})
            code_model = OpenAIServerModel(model_id="o4-mini", api_base=os.getenv("OPENAI_BASE_URL"), api_key=os.getenv("OPENAI_API_KEY"), max_tokens=200000, timeout=100, reasoning_effort="high", client_kwargs={"max_retries": 3})

            prompt_data = load_prompt_from_yaml(project_root / "prompts/augmented_question.yaml")
            augmented_question = prompt_data.format(original_question=example["question"])

            if example.get("file_name"):
                file_path_str = str(example['file_name'])
                if ".zip" in file_path_str:
                    unzipped_files = get_zip_files(file_path_str)
                    prompt_use_files = f"## ATTACHED FILE PATHS:\n{unzipped_files}\n\nThe attached zip file has been unzipped..."
                else:
                    prompt_use_files = f"\n## ATTACHED FILE PATH:\n{file_path_str}\n\nTo answer this question, you need to utilize the provided attached file..."
                augmented_question += prompt_use_files

            start_time = datetime.now()
            agent_logger.log_task_start(task_id, example.get('question', ''))
            
            output, intermediate_steps, final_exception = None, [], None
            iteration_limit_exceeded = False
            
            agent = create_agent_team(project_root, logger=agent_logger, manager_model=manager_model, search_model=search_model, code_model=code_model)
            with using_metadata({"task_id": task_id}):
                for attempt in range(2):
                    try:
                        output = agent.run(augmented_question)
                        intermediate_steps = agent.write_memory_to_messages()
                        if output and "Agent stopped due to iteration limit or time limit." in str(output):
                            iteration_limit_exceeded = True
                        break
                    except Exception as e:
                        agent_logger.log_error(traceback.format_exc())
                        final_exception = e
                        if attempt == 0:
                            agent_logger.log_error("Agent error, restarting...")
                            sleep(60)
                        else:
                            agent_logger.log_error(f"Agent failed after multiple attempts.")
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            status = "completed" if output and not iteration_limit_exceeded and not final_exception else "failed"
            agent_logger.log_task_end(task_id, duration, status)

            annotated_example = {
                "agent_name": manager_model.model_id, "task_id": task_id, "prediction": None,
                "prediction": output,
                "true_answer": example["true_answer"], "level": example["level"], "question": example["question"],
                "augmented_question": augmented_question, "intermediate_steps": intermediate_steps,
                "parsing_error": None, "iteration_limit_exceeded": iteration_limit_exceeded,
                "agent_error": str(final_exception) if final_exception else None,
                "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"), "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            append_answer(annotated_example, answers_file, append_answer_lock)
            print(f"Task {task_id} completed")
    finally:
        os.chdir(original_cwd)

def main():
    args = parse_args()
    project_root = Path(__file__).parent.resolve()
    
    if args.use_phoenix:
        register(project_name=args.run_name)
        SmolagentsInstrumentor().instrument()

    answers_file_path = project_root / f"output/{args.split}/{args.run_name}.jsonl"
    temp_answer_path = project_root / f"output/cache/{args.split}/{args.run_name}.jsonl"
    answers_file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_answer_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"🔄 Running agent tasks...")
    
    exist_task_ids = []
    if temp_answer_path.exists():
        with open(temp_answer_path, "r") as f:
            for line in f:
                exist_task_ids.append(json.loads(line)["task_id"])

    eval_ds = load_gaia_dataset(project_root / "data/gaia", args.split)
    task_to_run=eval_ds.to_list()
    # tasks_to_run = [record for record in eval_ds if record["task_id"] =="7bd855d8-463d-4ed5-93ca-5fe35145f733"]

    print(f"🎯 Running {len(tasks_to_run)} tasks. Results will be saved to: {answers_file_path}")
    
    with ThreadPoolExecutor(max_workers=args.concurrency) as exe:
        futures = [exe.submit(run_agent, example, args.run_name, str(temp_answer_path), project_root) for example in tasks_to_run]
        for f in tqdm(as_completed(futures), total=len(tasks_to_run), desc="Processing tasks"):
            f.result()
    
    print("✅ All tasks completed. Starting answer extraction...")
    run_extract(str(temp_answer_path), args.extract_model_id, extract_conv_num)
    print(f"✅ All tasks processed. Final results are in: {answers_file_path}")

if __name__ == "__main__":
    main()
