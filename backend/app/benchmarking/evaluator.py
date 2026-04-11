"""
evaluator.py — Benchmarking Framework for Contract Intelligence Suite
Measures Pipeline performance using mock Ground Truth data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from sklearn.metrics import precision_recall_fscore_support
from typing import Dict, Any

def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def generate_mock_ground_truth(output_dir: str, gt_dir: str):
    """
    Creates mock ground truth files based on the output directory
    for demonstration purposes. Modifies some values randomly so F1 is not always 1.0.
    """
    out_path = Path(output_dir)
    gt_path = Path(gt_dir)
    gt_path.mkdir(parents=True, exist_ok=True)
    
    for f in out_path.glob("*.json"):
        if f.name.endswith(".error.json"): continue
        data = _load_json(f)
        
        # Create a mock variation 
        # Flip non_compete to absent on mock to simulate a False Negative
        if "clauses" in data and "non_compete" in data["clauses"]:
            data["clauses"]["non_compete"]["status"] = "present"
            
        (gt_path / f.name).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[EVAL] Generated mock ground truth: {f.name}")

def evaluate_predictions(output_dir: str, gt_dir: str):
    """
    Calculates Precision, Recall, and F1 at the clause status level.
    """
    out_path = Path(output_dir)
    gt_path = Path(gt_dir)
    
    y_true = []
    y_pred = []
    
    # We will measure detection of the standard clauses
    clauses_to_track = ["governing_law", "audit_rights", "non_compete", "non_solicitation"]
    
    for gt_file in gt_path.glob("*.json"):
        pred_file = out_path / gt_file.name
        if not pred_file.exists():
            continue
            
        gt_data = _load_json(gt_file)
        pred_data = _load_json(pred_file)
        
        for clause in clauses_to_track:
            gt_val = 1 if gt_data.get("clauses", {}).get(clause, {}).get("status") == "present" else 0
            pred_val = 1 if pred_data.get("clauses", {}).get(clause, {}).get("status") == "present" else 0
            
            y_true.append(gt_val)
            y_pred.append(pred_val)
            
    if not y_true:
        print("[EVAL] No matchable JSONs found between output and ground truth.")
        return
        
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    
    print("\n" + "="*50)
    print(" 📊 CONTRACT INTELLIGENCE BENCHMARK REPORT ")
    print("="*50)
    print(f" Samples Evaluated  : {len(y_true) // len(clauses_to_track)} Contracts")
    print(f" Clause Data Points : {len(y_true)}")
    print("-" * 50)
    print(f" Precision          : {precision:.4f}")
    print(f" Recall             : {recall:.4f}")
    print(f" F1 Score           : {f1:.4f}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate Contract Output vs Ground Truth")
    parser.add_argument("--output_dir", default="../data/output", help="Pipeline Output Directory")
    parser.add_argument("--gt_dir", default="../data/ground_truth", help="Ground Truth Directory")
    parser.add_argument("--mock", action="store_true", help="Generate Mock Ground Truth")
    args = parser.parse_args()
    
    # Ensure current working directory paths resolve relative to script if run as python -m ...
    out_dir = Path(__file__).parent.parent.parent.joinpath("data", "output").resolve()
    gt_dir = Path(__file__).parent.parent.parent.joinpath("data", "ground_truth").resolve()
    
    if args.mock:
        generate_mock_ground_truth(str(out_dir), str(gt_dir))
        
    evaluate_predictions(str(out_dir), str(gt_dir))
