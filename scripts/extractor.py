# Shamelessly stolen from Microsoft Autogen team: thanks to them for this great resource!
# https://github.com/microsoft/autogen/blob/gaia_multiagent_v01_march_1st/autogen/browser_utils.py
import copy
import re
from smolagents.models import MessageRole, Model


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

                    ## Discussion Hisotry:
                    """,
                }
            ],
        }
    )

    if conv_num==0:
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

    # match = re.search(r"FINAL ANSWER:\s*([\s\S]+?)(?:\n\n|\Z)(?![\s\S]*FINAL ANSWER:)", response)
    # if match:
    #     final_answer = match.group(1).strip()
    # else:
    #     final_answer = response.split("FINAL ANSWER: ")[-1].strip()
    final_answer = response.split("FINAL ANSWER: ")[-1].strip()

    return final_answer