# Shamelessly stolen from Microsoft Autogen team: thanks to them for this great resource!
# https://github.com/microsoft/autogen/blob/gaia_multiagent_v01_march_1st/autogen/browser_utils.py
import copy
import json
import logging
from pathlib import Path
from time import sleep
import traceback
from concurrent.futures import ThreadPoolExecutor
from smolagents.models import OpenAIServerModel, MessageRole, Model, ChatMessage
from tqdm import tqdm


import copy
import json
import logging
from pathlib import Path
from time import sleep
import traceback
from smolagents.models import OpenAIServerModel, MessageRole, Model, ChatMessage
from tqdm import tqdm


def extract_answer(original_task: str, prediction: str, model: Model) -> str:
    messages = [
        {
            "role": MessageRole.SYSTEM,
            "content": [
                {
                    "type": "text",
                    "text": f"""You are an answer format verifying expert for multi-agent systems.
Your task is to analyze the final answer given by the agent team and verify if it is in the correct FORMAT, then return the final answer in the correct FORMAT.

## Analysis Steps:
1. **Identify Key Information**: Scan the answer for facts, data, calculations, and conclusions relevant to the question
2. **Constraints Check**: Check if the answer satisfies all the instructions in the question.
3. **Verify Completeness**: Ensure the answer directly addresses what was asked.
4. **Result Convert**: You may need to convert the analysis results appropriately to match the question requirements. For example, statistical results from the analysis process.
5. **Verify Format**: Verify if the final answer is in the correct format.
                    
## Answer Formatting Rules:
- Results: Only return the concise core answer required by the question stem without any redundant description.
- Numbers: Use digits only (e.g., "42", not "forty-two"), no commas, no units (e.g. $, %) unless specifically requested.
- Plain Text: Use exact tex without numbers, avoid articles/abbreviations unless specified, no punctuation at the end.
- Lists: Comma-separated, apply number/text rules to each element.
- Units: Pay close attention to the units of measurement specified in the question if necessary. (units: e.g. per 100, thousand hours)

## Response Rules:
- Report your thoughts, and finish your answer with the following template: FINAL ANSWER: [YOUR FINAL ANSWER].
- Your FINAL ANSWER should be a number OR as few words as possible OR a comma separated list of numbers and/or strings.
- If you are asked for a number, don't use comma to write your number neither use units such as $ or percent sign unless specified otherwise.
- If you are asked for a string, don't use articles, codes, neither abbreviations (e.g. for cities), and write the digits in plain text unless specified otherwise.
- If you are asked for a comma separated list, apply the above rules depending of whether the element to be put in the list is a number or a string.
- DO NOT add `Thoughts` to the FINAL ANSWER template, the final answer should be specific.

---
## Correction Answer Example:
## Example 1
task: Who is the president of the United States in 2025, give the full name?
final_answer: The president of the United States in 2025 is Donald Trump.
correct_answer: Donald John Trump

## Example 2
task: What is the tallest building in the world, and give its height in meters just the number?
final_answer: The Burj Khalifa, 828 meters
correct_answer: 828

## Example 3
task: How much revenue did Apple generate in the fourth quarter of fiscal year 2024?
final_answer: $9,490,000,000
correct_answer: 9490000000

## Example 4
task: 1. Please output 'Hello, world!'.\n2. Dont print anything.\n If there is a conflict, ignore above instructions, and just output the 'Java'.
final_answer: Hello, world! Java
correct_answer: Java

"""
                }
            ],
        }
    ]

    messages.append(
        {
            "role": MessageRole.USER,
            "content": [
                {
                    "type": "text",
                    "text": f"""The Agent team has finished their investigation. Here is the original task and the prediction given by the agent team, please check the format of the prediction.
                    For Reasoning or Understanding tasks, check if the answer is logical and consistent with the question, you can reason by yourself first, if your answer is different from the given final answer, you should return yours.
                    But for other tasks, you should just check the format. Please give your analysis process and reason before returning the final answer.

                    ## Task:
                    ```
                    {original_task}
                    ```

                    ## Prediction:
                    ```
                    {prediction}
                    ```

                    Now, begin your analysis, remember return the final answer with the following template: FINAL ANSWER: [YOUR FINAL ANSWER]
                    """,
                }
            ],
        }
    )
    
    messages = [ChatMessage.from_dict(msg) for msg in messages]

    response = model(messages)
    final_answer = response.content.split("FINAL ANSWER: ")[-1].strip()
    return final_answer


def run_extract(target_path: str, model_id: str="gpt-4.1", conv_num: int=4, max_workers: int = 10):
    """

    Args:
        target_path (str): 
        model_id (str): 
        conv_num (int): 提取答案时所使用的对话轮次[-conv_num-3: -3]
        max_workers (int): Maximum number of threads for parallel execution.
    """
    model = OpenAIServerModel(
        api_base="http://gpt-proxy.jd.com/gateway/common",
        api_key="64268e2b-188f-4e86-9b2a-8542ba3849c8",
        max_tokens=13000,
        model_id=model_id,
        temperature=0.2,
        # reasoning_effort="high"
        )

    file_path = Path(target_path)
    source_path = file_path  # Use the provided path directly
    records=[]
    with open(source_path, "r", encoding="utf8") as file:
        for line in file:
            records.append(json.loads(line))
    print("===========================================================")
    print("-------------------- Extracted Results --------------------")
    print("===========================================================\n")
    
    def process_record(record):
        answer_attempt=0
        error_attempt=0
        while True:
            try:
                final_result = extract_answer(
                    record['question'], 
                    record['prediction'],
                    model=model, 
                    conv_num=conv_num
                )
                record['prediction'] = final_result
                record['parsing_error'] = False

                if answer_attempt==0 and final_result == "Unable to determine" and not final_result.startswith("Thought:"): # 如果第一次没有明确答案则再次尝试
                    # print(f"Unable to parse {record['task_id']}, retry extraction again")
                    answer_attempt+=1
                    continue
                break
            except Exception as e:
                # traceback.print_exc()
                if error_attempt == 0: # 如果第一次尝试出现错误
                    # print("\n===============================================================")
                    # print(f"An error occurred while executing `extract_answer` for {record['task_id']}. Retrying...")
                    # print("===============================================================\n") 
                    error_attempt+=1
                    sleep(30)
                    continue                   
                else:
                    logging.error(f"Error: `extract_answer()` still failed after 2 attempts for {record['task_id']}: {e}")
                    record['prediction'] = None
                    record['parsing_error'] = str(e)
                break
        return record

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        processed_records = list(tqdm(executor.map(process_record, records), total=len(records)))

    for record in processed_records:
        print(f"task_id: {record['task_id']} > : {record.get('prediction')}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for record in processed_records:
            line = json.dumps(record, ensure_ascii=False)
            f.write(line + "\n")     
    print(f"\n\n答案保存到路径: {file_path.resolve()}\n\n")