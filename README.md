# Benchmark for Retrieving Information in EHRs (BRIE) Phase 1

To install the dependencies, run:

```
cd synthetic-qa
pip install -e .
```

To run complete pipeline. Make sure you change the paths in `run_generation_question_phase1.sh`.

```
chmod +x src/synthetic_qa/run_generation_question_phase1.sh
./src/synthetic_qa/run_generation_question_phase1.sh
```

This repository requires the user to supply a Gemini Pro 2.5 API key and endpoint. (See `src/synthetic_qa/utils.py`)

Note that prompt examples have been heavily redacted to avoid leaking PHI. 
