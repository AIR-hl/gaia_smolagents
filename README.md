# 基于 smolagents 框架的GAIA项目

## 数据集下载

获取[gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA)数据集，放置于 `data`路径下

## Agent启动！

直接运行启动，自定义当前运行名称 (`run_name`)与并发数 (`concurrency `)。日志在logs下按照  `task_id `保存；各程序运行在独立 `workspace `，下载内容按 `task_id`存储

```shell
python run_gaia.py --run_name "your_run_name" --concurrency 10
```

可以访问phoenix cloud查看trace记录

## 结果评估

执行下面的命令可以获取 `output`下各执行的评估结果

```shell
python evaluate_result.py
```
