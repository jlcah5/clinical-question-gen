# synthetic-qa

To install the dependencies, run:

```
cd synthetic-qa
pip install -e .
```

To run complete pipeline

```
chmod +x src/synthetic_qa/run_generation_question_phase1.sh
./src/synthetic_qa/run_generation_question_phase1.sh
```

This repository examples the user to supply a Gemini Pro 2.5 API key and endpoint.
Note that prompt examples have been heavily redacted to avoid leaking PHI. 