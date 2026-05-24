"""
scripts/fine_tune.py
Fix #8 — Fine-tunes BERT on the Amazon QA dataset for e-commerce domain accuracy.

Usage:
    pip install datasets accelerate
    python scripts/fine_tune.py --output_dir models/bert-amazon-qa --epochs 3

The fine-tuned model is saved locally and can be used in QAModel by changing:
    EN_MODEL = "models/bert-amazon-qa"
"""

import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fine_tuner")

BASE_MODEL  = "deepset/bert-base-cased-squad2"   # start from already-fine-tuned checkpoint
DATASET_ID  = "amazon_qa"                         # HuggingFace Hub dataset


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--output_dir", default="models/bert-amazon-qa")
    p.add_argument("--epochs",     type=int,   default=3)
    p.add_argument("--batch_size", type=int,   default=16)
    p.add_argument("--lr",         type=float, default=3e-5)
    p.add_argument("--max_samples",type=int,   default=50_000,
                   help="Cap training samples to keep training time manageable")
    p.add_argument("--max_length", type=int,   default=384)
    p.add_argument("--doc_stride", type=int,   default=128)
    return p.parse_args()


def load_amazon_qa(max_samples: int):
    """
    Loads Amazon QA dataset and converts it to SQuAD-format dicts.
    Amazon QA has: questionText, answerText, asin, category.
    We use the answer as the span and the product description as context.
    """
    from datasets import load_dataset
    logger.info("Loading %s dataset (this may take a few minutes)…", DATASET_ID)
    ds = load_dataset(DATASET_ID, split="train", streaming=True)

    examples = []
    for item in ds:
        if len(examples) >= max_samples:
            break
        q = item.get("questionText", "").strip()
        a = item.get("answerText",   "").strip()
        if not q or not a or len(a) > 200:
            continue
        # Use the answer as both context and answer span (extractive style)
        context = a
        examples.append({
            "id":      str(len(examples)),
            "title":   item.get("asin", "product"),
            "context": context,
            "question": q,
            "answers": {
                "text":          [a],
                "answer_start":  [0],
            }
        })

    logger.info("Loaded %d training examples", len(examples))
    return examples


def tokenize_and_align(examples, tokenizer, max_length, doc_stride):
    """Standard SQuAD tokenisation for extractive QA training."""
    tokenized = tokenizer(
        examples["question"],
        examples["context"],
        truncation="only_second",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )

    sample_mapping  = tokenized.pop("overflow_to_sample_mapping")
    offset_mapping  = tokenized.pop("offset_mapping")
    answers         = examples["answers"]

    start_positions, end_positions = [], []

    for i, offsets in enumerate(offset_mapping):
        sample_idx   = sample_mapping[i]
        answer       = answers[sample_idx]
        start_char   = answer["answer_start"][0]
        end_char     = start_char + len(answer["text"][0])
        sequence_ids = tokenized.sequence_ids(i)

        # Find the span of context tokens
        ctx_start = next((j for j, s in enumerate(sequence_ids) if s == 1), None)
        ctx_end   = next((j for j in range(len(sequence_ids)-1, -1, -1)
                          if sequence_ids[j] == 1), None)

        if ctx_start is None or ctx_end is None:
            start_positions.append(0)
            end_positions.append(0)
            continue

        token_start = token_end = 0
        for j in range(ctx_start, ctx_end + 1):
            if offsets[j][0] <= start_char < offsets[j][1]:
                token_start = j
            if offsets[j][0] < end_char <= offsets[j][1]:
                token_end = j

        start_positions.append(token_start)
        end_positions.append(token_end)

    tokenized["start_positions"] = start_positions
    tokenized["end_positions"]   = end_positions
    return tokenized


def fine_tune(args):
    from transformers import (
        AutoTokenizer, AutoModelForQuestionAnswering,
        TrainingArguments, Trainer, DefaultDataCollator
    )
    from datasets import Dataset
    import torch

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load tokenizer + model
    logger.info("Loading base model: %s", BASE_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model     = AutoModelForQuestionAnswering.from_pretrained(BASE_MODEL)

    # Load data
    raw_examples = load_amazon_qa(args.max_samples)
    dataset = Dataset.from_list(raw_examples)
    split   = dataset.train_test_split(test_size=0.05, seed=42)

    # Tokenise
    logger.info("Tokenising dataset…")
    tok_fn = lambda ex: tokenize_and_align(ex, tokenizer, args.max_length, args.doc_stride)
    train_ds = split["train"].map(tok_fn,  batched=True, remove_columns=dataset.column_names)
    eval_ds  = split["test"].map(tok_fn,   batched=True, remove_columns=dataset.column_names)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        fp16=torch.cuda.is_available(),
        logging_steps=100,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        tokenizer=tokenizer,
        data_collator=DefaultDataCollator(),
    )

    logger.info("Starting fine-tuning for %d epochs…", args.epochs)
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    logger.info("Fine-tuned model saved to %s", output_dir)
    logger.info("Update src/models/qa_model.py: EN_MODEL = '%s'", output_dir)


if __name__ == "__main__":
    args = parse_args()
    fine_tune(args)
