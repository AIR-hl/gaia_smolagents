import json
import traceback
from smolagents import (
    Model,
    OpenAIServerModel
)
from typing import Any
import argparse
import copy
import os
from smolagents.models import MessageRole, Model
from datetime import datetime

def extract_answer(original_task: str, inner_messages, model: Model, conv_num:int=0) -> str:
    messages = [
        {
            "role": MessageRole.SYSTEM,
            "content": [
                {
                    "type": "text",
                    "text": f"""You are an answer-exctracting expert for multi-agent systems. Your task is to analyze team discussions and extract the final answer to a specific question."""
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
                    "text": f"""The Agent team has finished their investigation. I will provide you a part of their discussion history, the answer may lie in the conversation.

                    ## Task:
                    Please analyze the history conversation, then summurize and extract the specific FINAL ANSWER of the question. Please ensure that the answer is correct and reasonable.

                    ## Original Question:
                    {original_task}

                    ## Analysis Steps:
                    1. **Identify Key Information**: Scan the conversation for facts, data, calculations, and conclusions relevant to the question
                    2. **Trace the Logic**: Follow the team's reasoning process and identify the most reliable conclusions
                    3. **Resolve Conflicts**: If there are contradictory statements, prioritize the most recent, well-supported, or authoritative information
                    4. **Verify Completeness**: Ensure the answer directly addresses what was asked.
                    5. **Result Convert**: You may need to convert the analysis results appropriately to match the question requirements. For example, statistical results from the analysis process.
                    
                    ## Answer Formatting Rules:
                    - Results: Only return the concise core answer required by the question stem without any redundant description.
                    - Numbers: Use digits only (e.g., "42", not "forty-two"), no commas, no units (e.g. $, %) unless specifically requested.
                    - Plain Text: Use exact tex without numbers, avoid articles/abbreviations unless specified, no punctuation at the end.
                    - Lists: Comma-separated, apply number/text rules to each element.
                    - Units: Pay close attention to the units of measurement specified in the question if necessary. (units: e.g. per 1000, per million)
                    - Precision: Ensure the numerical answer matches the specified rounding precision in the question. (e.g. thousandths, two decimal places)


                    ## Response Rules:
                    - Report your thoughts, and finish your answer with the following template: FINAL ANSWER: [YOUR FINAL ANSWER].
                    - Your FINAL ANSWER should be a number OR as few words as possible OR a comma separated list of numbers and/or strings.
                    - If you are asked for a number, don't use comma to write your number neither use units such as $ or percent sign unless specified otherwise.
                    - If you are asked for a string, don't use articles, codes, neither abbreviations (e.g. for cities), and write the digits in plain text unless specified otherwise.
                    - If you are asked for a comma separated list, apply the above rules depending of whether the element to be put in the list is a number or a string.
                    - DO NOT add `Thoughts` to the FINAL ANSWER template, the final answer should be specific.
                    
                    ## Discussion Hisotry:
                    """,
                }
            ],
        }
    )

    if conv_num==0 or conv_num+3>=len(inner_messages):
        start=0
    else:
        start=-3-conv_num

    try:
        for message in inner_messages[start:-3]:
            if not message.get("content"):
                continue
            message = copy.deepcopy(message)
            # message["role"] = MessageRole.USER
            messages.append(message)
    except Exception:
        messages += [{"role": MessageRole.ASSISTANT, "content": str(inner_messages)}]


    messages.append({
            "role": MessageRole.USER,
            "content": [{
                    "type": "text",
                    "text": "Start your answer extraction task."
                }],
            }
    )
    response = model(messages).content

    final_answer = None

    final_answer = response.split("FINAL ANSWER: ")[-1].strip()

    return final_answer

def process_record(record, model, conv_num, max_attempts=2):
    for attempt in range(max_attempts):
        try:
            final_result = extract_answer(
                record['question'], 
                record['intermediate_steps'],  # 注意：这里可能是 'intermediate_steps'（拼写检查）
                model=model, 
                conv_num=conv_num
            )
            record['prediction'] = final_result
            record['parsing_error'] = False

            if final_result == "Unable to determine":
                print(f"Unable to parse {record['task_id']}, retry extraction again")
                continue
            break
        except Exception as e:
            traceback.print_exc()
            if attempt == max_attempts - 1:
                print(f"!!! extract_answer() failed after {max_attempts} attempts.")
                record['prediction'] = None
                record['parsing_error'] = str(e)
            else:
                print("\n===============================================================")
                print("An error occurred while executing 'extract_answer'. Retrying...")
                print("===============================================================\n")
    print(f"task_id: {record['task_id']} > final_answer: {final_result}")
    return record

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", type=str, default="o4-mini")
    parser.add_argument("--file_path", type=str, default="")
    parser.add_argument("--conv_num", type=int, default=5)
    parser.add_argument("--max_tokens", type=int, default=50000)
    parser.add_argument("--run_name", type=str, default="")
    return parser.parse_args()
    
if __name__=="__main__":
    args = parse_args()
    custom_role_conversions = {"tool-call": "assistant", "tool-response": "user"}
    if args.run_name == "":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.run_name = "gaia_" + timestamp

    model_params: dict[str, Any] = {
        "model_id": args.model_name,
    }
    model_params["max_tokens"] = args.max_tokens
    model_params['temperature']=0.2
    model = OpenAIServerModel(
        api_base="http://gpt-proxy.jd.com/gateway/common",
        api_key="64268e2b-188f-4e86-9b2a-8542ba3849c8",
        **model_params
    )
    
    records = []
    with open(args.file_path, "r", encoding='utf-8') as file:
        for line in file:
            records.append(json.loads(line))

    processed_records = []
    for record in records:
        try:
            result = process_record(record, model, args.conv_num)
            processed_records.append(result)
        except Exception as e:
            print(f"Error processing record: {e}")
            traceback.print_exc()

    output_dir = os.path.dirname(args.file_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_file = os.path.join(output_dir, args.run_name+".jsonl")
    with open(output_file, 'w', encoding='utf-8') as file:
        for item in processed_records:
            line = json.dumps(item, ensure_ascii=False)
            file.write(line + "\n")