"""RAGAS evaluation wrapper."""

from typing import Any


async def evaluate_run(
    question: str,
    answer: str,
    contexts: list[str],
    golden_answer: str | None = None,
    golden_contexts: list[str] | None = None,
) -> dict[str, float]:
    """Compute RAGAS metrics for a single QA pair."""
    try:
        from datasets import Dataset as HFDataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        data = {
            "question": [question],
            "answer": [answer],
            "contexts": [contexts],
        }
        if golden_answer:
            data["ground_truth"] = [golden_answer]

        dataset = HFDataset.from_dict(data)

        metrics = [faithfulness, answer_relevancy]
        if golden_answer:
            metrics += [context_precision, context_recall]

        result = evaluate(dataset, metrics=metrics)
        return dict(result)
    except ImportError:
        # TODO: install ragas and datasets packages
        return {"faithfulness": 0.0, "answer_relevancy": 0.0, "note": "ragas not installed"}


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    """Average metrics across multiple eval results."""
    if not results:
        return {}
    keys = [k for k in results[0] if isinstance(results[0][k], (int, float))]
    return {k: sum(r.get(k, 0.0) for r in results) / len(results) for k in keys}
