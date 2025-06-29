import argparse
import glob
import os
from IPython.display import display

import datasets
import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import login
import re
from collections import Counter
from scripts.judge import check_close_call, question_scorer

# 设置 pandas 显示选项，确保终端中完整输出
pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)  # 自动适应终端宽度
pd.set_option("display.max_colwidth", None)  # 显示完整内容，不截断

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=str, default="validation")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    OUTPUT_DIR = "output"
    SPLIT=args.split
    # 加载数据集
    eval_ds = datasets.load_dataset(
        "data/gaia/GAIA.py",
        name="2023_all",
        split="validation",
        trust_remote_code=True
    )

    eval_ds = eval_ds.rename_columns({"Question": "question", "Final answer": "true_answer", "Level": "task"})
    eval_df = pd.DataFrame(eval_ds)

    # 加载结果文件
    results = []
    for f in glob.glob(f"{OUTPUT_DIR}/{SPLIT}/*.jsonl"):
        df = pd.read_json(f, lines=True)
        df["agent_name"] = os.path.basename(f).split(".")[0]  # 更安全的文件名提取方式
        results.append(df)

    if not results:
        print(f"未找到任何结果文件，请检查路径: {OUTPUT_DIR}/validation/")
        exit()

    result_df = pd.concat(results)
    result_df["prediction"] = result_df["prediction"].fillna("No prediction")

    # 计算正确性
    result_df["is_correct"] = result_df.apply(lambda x: question_scorer(x["prediction"], x["true_answer"]), axis=1)
    result_df["is_near_correct"] = result_df.apply(
        lambda x: check_close_call(x["prediction"], x["true_answer"], x["is_correct"]),
        axis=1,
    )

    result_df["count_steps"] = result_df["intermediate_steps"].apply(len)

    # 辅助函数
    def find_attachment(question):
        matches = eval_df.loc[eval_df["question"].apply(lambda x: x in question), "file_name"]
        return matches.values[0].split(".")[-1] if len(matches) > 0 else "None"

    result_df["attachment_type"] = result_df["question"].apply(find_attachment)

    def get_durations(row):
        duration_timedelta = row["end_time"] - row["start_time"]
        return int(duration_timedelta.total_seconds())

    result_df["duration"] = result_df.apply(get_durations, axis=1)

    # 准备最终数据
    sel_df = result_df.drop_duplicates(subset=["agent_name", "question"]).copy()

    # 终端输出结果
    def print_divider(title=None):
        print("\n" + "=" * 50)
        if title:
            print(f"=== {title.upper()} ===")
            print("=" * 50)


    def weighted_acc(group: pd.DataFrame) -> float:
        # ① 各 level 样本数 → 权重
        cnts = group['level'].value_counts()
        weights = cnts / cnts.sum()          # w1,w2,w3 …
        print(weights)
        # ② 各 level 的准确率
        acc_per_level = group.groupby('level')['is_correct'].mean()
        
        # ③ 按索引对齐后相乘并求和
        return (weights * acc_per_level).sum()

    # 计算所有 agent 的加权准确率
    scores = (
        sel_df.groupby('agent_name')
            .apply(weighted_acc)     # 每组调用自定义函数
            .round(3)                # 保留三位小数
            .to_string()
    )


    print_divider("整体分数")
    # print(sel_df.groupby("agent_name")[["is_correct"]].mean().round(3).to_string())
    print(scores)

    print_divider("完成任务数")
    print(sel_df["agent_name"].value_counts().to_string())

    print_divider("完成情况分布")
    print(sel_df.groupby("agent_name")[["level"]].value_counts().to_string())

    print_divider("准确率详情")
    print(
        sel_df.groupby(["agent_name", "level"])[["is_correct", "is_near_correct", "count_steps", "question", "duration"]]
        .agg({
            "is_correct": "mean",
            "is_near_correct": "mean",
            "count_steps": "mean",
            "question": "count",
            "duration": "mean",
        })
        .rename(columns={"question": "count"})
        .round(3)
        .to_string()
    )