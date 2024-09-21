"""
Runs retrieval evaluation on the given dataset.
"""

import ast
import re
import collections
from typing import List, Tuple, Optional, Dict
import re
import argparse
import json
import os
from datasets import load_dataset
from typing import List
from utils.preprocess_data import get_repo_files
from collections import defaultdict
from tabulate import tabulate

def load_json(filepath):
    return json.load(open(filepath, "r"))

def load_jsonl(filepath):
    """
    Load a JSONL file from the given filepath.

    Arguments:
    filepath -- the path to the JSONL file to load

    Returns:
    A list of dictionaries representing the data in each line of the JSONL file.
    """
    with open(filepath, "r") as file:
        return [json.loads(line) for line in file]


class CodeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.structures = []

    def visit_ClassDef(self, node):
        self.structures.append(('class', node.name, node.lineno, node.end_lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        for parent in self.structures:
            if parent[0] == 'class' and parent[2] <= node.lineno <= parent[3]:
                self.structures.append(('function', f"{parent[1]}.{node.name}",
                                        node.lineno, node.end_lineno))
                break
        else:
            self.structures.append(('function', node.name, node.lineno, node.end_lineno))
        self.generic_visit(node)

def parse_file_structure(file_content: str) -> List[Tuple[str, str, int, int]]:
    """
    Parse the file content and return a list of tuples containing information about
    classes, methods, and functions.

    Args:
    file_content (str): The content of the file to parse.

    Returns:
    List[Tuple[str, str, int, int]]: A list of tuples, each containing
                                     (type, name, start_line, end_line).
    """
    tree = ast.parse(file_content)
    visitor = CodeVisitor()
    visitor.visit(tree)
    return visitor.structures

def find_structure_for_line(structures: List[Tuple[str, str, int, int]], line_number: int) -> Optional[Tuple[str, str, int, int]]:
    """
    Find the innermost structure (class, method, or function) that contains the given line number.

    Args:
    structures (List[Tuple[str, str, int, int]]): List of structures in the file.
    line_number (int): The line number to search for.

    Returns:
    Optional[Tuple[str, str, int, int]]: The structure containing the line, or None if not found.
    """
    matching_structures = [s for s in structures if s[2] <= line_number <= s[3]]
    return max(matching_structures, key=lambda s: s[2]) if matching_structures else None


def find_structure_for_lines(file_content: str, line_numbers: List[int]) -> Dict[int, Optional[Tuple[str, str, int, int]]]:
    """
    Find the structures (class, method, or function) for the given line numbers in a file.

    Args:
    file_path (str): Path to the file.
    line_numbers (List[int]): List of line numbers to search for.

    Returns:
    Dict[int, Optional[Tuple[str, str, int, int]]]: A dictionary mapping line numbers to their containing structures.
    """

    
    structures = parse_file_structure(file_content)
    return {line: find_structure_for_line(structures, line) for line in line_numbers}


def get_affected_files(patch_string):
    pattern = r'diff --git a/(.*?) b/(.*?)$'
    matches = re.findall(pattern, patch_string, re.MULTILINE)
    affected_files = set()
    for match in matches:
        affected_files.add(match[0])  # 'a' path
        affected_files.add(match[1])  # 'b' path
    
    return list(affected_files)


def get_retrieval_eval_results(swe_bench_data, pred_jsonl_path):
    pred_data = load_jsonl(pred_jsonl_path)
    repo_metrics = defaultdict(lambda: {'precision': 0, 'recall': 0, 'precision_all': 0, 'recall_all': 0, 'count': 0, 'count_all': 0})

    pred_dict = {pred["instance_id"]: pred for pred in pred_data if "instance_id" in pred}

    for instance in swe_bench_data:
        instance_id = instance["instance_id"]
        gt_patch = instance["patch"]
        gt_files = get_affected_files(gt_patch)
        repo_name = instance["instance_id"].split("__")[0]
        
        repo_metrics[repo_name]['count_all'] += 1

        if instance_id not in pred_dict or "model_patch" not in pred_dict[instance_id]:
            continue

        pred_patch = pred_dict[instance_id]["model_patch"]
        pred_files = get_affected_files(pred_patch)

        intersection = set(gt_files) & set(pred_files)
        recall = len(intersection) / len(gt_files) if gt_files else 1.0
        precision = len(intersection) / len(pred_files) if pred_files else 1.0

        repo_metrics[repo_name]['precision'] += precision
        repo_metrics[repo_name]['recall'] += recall
        repo_metrics[repo_name]['precision_all'] += precision
        repo_metrics[repo_name]['recall_all'] += recall
        repo_metrics[repo_name]['count'] += 1

    # Calculate averages and prepare table data
    table_data = []
    total_metrics = {'precision': 0, 'recall': 0, 'precision_all': 0, 'recall_all': 0, 'count': 0, 'count_all': 0}

    for repo, metrics in repo_metrics.items():
        count = metrics['count']
        count_all = metrics['count_all']
        avg_precision = metrics['precision'] / count if count > 0 else 0
        avg_recall = metrics['recall'] / count if count > 0 else 0
        avg_precision_all = metrics['precision_all'] / count_all if count_all > 0 else 0
        avg_recall_all = metrics['recall_all'] / count_all if count_all > 0 else 0
        
        table_data.append([
            repo, f"{avg_precision:.4f}", f"{avg_recall:.4f}", count,
            f"{avg_precision_all:.4f}", f"{avg_recall_all:.4f}", count_all, count_all - count
        ])
        
        # Accumulate totals
        for key in total_metrics:
            total_metrics[key] += metrics[key]

    # Calculate overall averages
    total_count = total_metrics['count']
    total_count_all = total_metrics['count_all']
    overall_avg_precision = total_metrics['precision'] / total_count if total_count > 0 else 0
    overall_avg_recall = total_metrics['recall'] / total_count if total_count > 0 else 0
    overall_avg_precision_all = total_metrics['precision_all'] / total_count_all if total_count_all > 0 else 0
    overall_avg_recall_all = total_metrics['recall_all'] / total_count_all if total_count_all > 0 else 0

    # Add overall row to table data
    table_data.append([
        "OVERALL", f"{overall_avg_precision:.4f}", f"{overall_avg_recall:.4f}", total_count,
        f"{overall_avg_precision_all:.4f}", f"{overall_avg_recall_all:.4f}", total_count_all, total_count_all - total_count
    ])

    return table_data

if __name__ == "__main__":
    # use parser
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_id", type=str, default="princeton-nlp/SWE-bench_Verified")
    parser.add_argument("--split_name", type=str, default="test")
    parser.add_argument("--preds_path", type=str, default="")
    args = parser.parse_args()

    assert args.preds_path != ""

    # load the dataset 
    swe_bench_data = load_dataset(args.dataset_id, split=args.split_name)

    table_data = get_retrieval_eval_results(swe_bench_data, args.preds_path)
    
    headers = [
        "Repo", "Precision", "Recall", "Count",
        "Precision (All)", "Recall (All)", "Count (All)", "Missing"
    ]
    
    print(tabulate(table_data, headers=headers, tablefmt="grid"))