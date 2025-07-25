import argparse
import json

import datasets
from src.scorer import question_scorer
import os

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str, default=None)
    return parser.parse_args()

if __name__=="__main__":
    args = parse_args()
    
    data=[]
    with open(args.file_path, "r", encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line))
    root_dir=args.file_path.split("/")[0]
    file_name=args.file_path.split("/")[-1]
    sorted_data=sorted(data, key=lambda x: x['task_id'])

    eval_ds = datasets.load_dataset(
        "data/gaia/GAIA.py",
        name="2023_all",
        split='validation',
        trust_remote_code=True,
        data_files={"validation": "2023/validation/metadata.jsonl", "test": "2023/test/metadata.jsonl"},
        # data_files={"validation": "/Users/liyang.1236/Documents/python_project/gaia_agents/data/gaia/2023/validation/metadata_11_20.jsonl", "test": "2023/test/metadata.jsonl"},
    )
    
    task_with_file=set()
    for item in eval_ds:
        if item['file_name']:
            task_with_file.add(item['task_id'])

    dir_path=os.path.join(root_dir, "comparing")
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)
    with open(os.path.join(dir_path, "compare-"+file_name), "w", encoding="utf-8") as f:
        for item in sorted_data:
            record={}
            record['task_id']=item['task_id']
            record['prediction']=item['prediction']
            record['true_answer']=item['true_answer']
            record['is_correct']=int(question_scorer(item["prediction"], item["true_answer"]))
            record['use_file']=int(item['task_id'] in task_with_file)
            record['level']=item['level']
            record['question']=item['question']
            record['error_type']= item['agent_error'] if item['agent_error'] else item['agent_error']
            line = json.dumps(record, ensure_ascii=False)
            f.write(line + "\n")  