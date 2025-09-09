#! /bin/bash

# change to file directory
cd "$(dirname "$0")"

# get input of person_ids
INPUT_FILE=""
NOTES_DIR=""
FACTS_DIR=""
QUESTIONS_DIR=""
PHASE1_DIR=""

# format into comma separated list
id_list=$(tail -n +2 $INPUT_FILE | cut -d',' -f2 | head -n 1 | paste -sd',' -)
# pull data and format
python format_data.py --id $id_list \
    --prefix ${NOTES_DIR}

# TODO: refactor all the flag names to be what they are
# extract the reason for admission
python process_hp.py --id ${id_list} \
    --input ${NOTES_DIR} \
    --output ${PHASE1_DIR}

# extract the facts
python extract_facts.py --id $id_list \
    --input ${NOTES_DIR} \
    --output ${FACTS_DIR}

# run fact generation
python generate_questions.py --id $id_list \
    --input ${FACTS_DIR} \
    --note ${NOTES_DIR} \
    --output ${QUESTIONS_DIR}

# prepare annotation files
python sample_questions.py \
    --id ${id_list} \
    --input ${QUESTIONS_DIR} \
    --note ${NOTES_DIR} \
    --output ${PHASE1_DIR} 

# run llm-as-a-judge
python filter_questions.py \
    --id ${id_list} \
    --input ${QUESTIONS_DIR} \
    --note ${NOTES_DIR} \
    --output ${PHASE1_DIR} 

