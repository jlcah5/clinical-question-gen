# default
import argparse
import os
import re
import random

import logging
import tqdm
import json
import concurrent.futures

# pip
import pandas as pd


# Regex to check if fact ends with (YYYY-MM-DD)
PATTERN = r"\(\d{4}-\d{2}-\d{2}\)$"
BATCH_SIZE = 500 # batch size to find duplicate facts
CHUNK_SIZE= 20000 # amount to chunk notes by
MAX_WORKERS=12 # number of threads to run


# custom
from prompts.extract_facts import EXTRACT_SYS, DEDUP_SYS, format_extract, format_dedup
from utils import load_notes, send_single_message

# setting the seed
random.seed(42)

def apply_facts_module(note_date, text):
    """
    Extract list of atomic facts from the note
    """
    user_input = format_extract(note_date=note_date,
                                text=text)
    response = send_single_message(system_instructions=EXTRACT_SYS,
                               user_prompt=user_input)
    return json.loads(response[7:-3])['claims']

def apply_redundancy_module(fact_list):
    """
    Return indices of redundant facts from fact list
    """
    user_input = format_dedup(input_fact_list=fact_list)
    response = send_single_message(system_instructions=DEDUP_SYS,
                                    user_prompt=user_input)
    # extracting JSON in case there is an explanation
    match = re.search(r"```(.*?)```", response, re.DOTALL)
    if match:
        response= match.group(0).strip()
    return json.loads(response[7:-3])['redundant_fact_indices']
    # return [int(i) for i in response if i.isdigit() ]


def shuffle_with_mapping(original_list):
    """
    Shuffles a list and returns the shuffled list and a mapping to the original indices.

    Args:
        original_list (list): The list to shuffle.

    Returns:
        tuple: A tuple containing the shuffled list and a list of original indices.
    """
    n = len(original_list)
    indices = list(range(n))
    random.shuffle(indices) # Shuffle the indices, not the list itself

    # Use the shuffled indices to create the new, shuffled list
    shuffled_list = [original_list[i] for i in indices]

    # Create the mapping: `shuffled_index -> original_index`
    mapping = {new_idx: old_idx for new_idx, old_idx in enumerate(indices)}
    
    return shuffled_list, mapping

def chunk_facts(facts_list, batch_size=BATCH_SIZE):
    """
    Helper function to batches fact list
    """
    
    return [
        (i, facts_list[i:i+batch_size])
        for i in range(0, len(facts_list), batch_size)
    ]
    # returns list of (start_index, batch_facts)

def run_within_batch_deduplication(facts_list,  batch_size=BATCH_SIZE, max_workers=MAX_WORKERS):
    """
    Helper function:
    1. batches shuffled list
    2. returns duplicate indices
    """
    to_remove = set()
    batches = chunk_facts(facts_list, batch_size)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                apply_redundancy_module,
                {start_idx + i: fact for i, fact in enumerate(batch)}
            ): start_idx
            for start_idx, batch in batches
        }

        for future in concurrent.futures.as_completed(futures):
            try:
                redundant = future.result()
                to_remove.update(redundant)
            except Exception as e:
                logging.info(f"Error in within-batch deduplication: {e}")
                continue

    return to_remove

def run_cross_batch_deduplication(facts_list, keep_indices, batch_size=BATCH_SIZE, max_workers=MAX_WORKERS):
    """
    Helper function
    1. shuffles the fact list
    2. batches shuffled list
    3. returns duplicate indices
    """
    to_remove = set()

    # shuffle the kept facts list
    keep_facts_shuffled, keep_indices_mapping = shuffle_with_mapping(
        [facts_list[i] for i in keep_indices]
    )
    groups = chunk_facts(keep_facts_shuffled, batch_size)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                apply_redundancy_module,
                {start_idx + i: fact for i, fact in enumerate(group)}
            ): (start_idx, group)
            for start_idx, group in groups
        }

        for future in concurrent.futures.as_completed(futures):
            try:
                redundant = future.result()
                # ignore indices that are out of bounds
                global_redundant = [
                    keep_indices_mapping[i] for i in redundant if i < len(keep_indices)
                ]
                to_remove.update(global_redundant)
            except Exception as e:
                logging.info(f"Error in cross-batch deduplication: {e}")
                continue

    return to_remove

def deduplicate_facts(facts_list, max_iter=3, threshold=5):
    """
    Function to remove duplicate facts
    1. Remove within batch
    2. Iteratively remove across batches until threshold or max iterations are met
    """
    all_to_remove = set()

    # Remove within batches (these are notes close together)
    # Within-batch pass
    batch_removals = run_within_batch_deduplication(facts_list)
    logging.info(f'Batch Removals: {batch_removals}')
    all_to_remove.update(batch_removals)

    keep_indices = [i for i in range(len(facts_list)) if i not in all_to_remove]

    
    # shuffle the list and then remove duplicates until very few are left
    for idx in range(max_iter):
        # Cross-batch pass
        original_size = len(all_to_remove)
        cross_removals = run_cross_batch_deduplication(facts_list, keep_indices)
        all_to_remove.update(cross_removals)
        logging.info(f'Index {idx}: Cross Removals: {cross_removals}')

        new_size = len(all_to_remove)
        if new_size - original_size < threshold:
            break
    # deduplicate at the end of the iteration
    deduped_list = [facts_list[i] for i in range(len(facts_list)) if i not in all_to_remove]

    return deduped_list, all_to_remove


def chunk_note(text: str, chunk_size: int):
    """Split note text into fixed-size chunks."""
    if len(text) < chunk_size:
        return [text]
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def process_chunk(row, chunk_idx, chunk, pattern):
    """Process one chunk: send to Gemini, parse, return structured dict + facts."""
    temp = {
        "note_number": row.name,
        "note_date": str(row["note_date"]),
        "note_title": row["note_title"],
        "chunk_num": chunk_idx,
        "text": chunk,
        "facts": []
    }

    facts = []
    for f in apply_facts_module(note_date=temp["note_date"], text=chunk):
        if re.search(pattern, f):
            fact = f"{f}"
        else:
            fact = f"{f} ({row['note_date'].date()})"
        facts.append(fact)

    temp["facts"].extend(facts)
    return temp, facts


def extract_facts_from_notes(notes_df, chunk_size, pattern, max_workers=MAX_WORKERS):
    fact_dict = []
    all_facts = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for row_idx, row in notes_df.iterrows():
            chunk_list = chunk_note(row["text"], chunk_size)
            for chunk_idx, chunk in enumerate(chunk_list):
                futures.append(
                    executor.submit(process_chunk, row, chunk_idx, chunk, pattern)
                )

        for future in concurrent.futures.as_completed(futures):
            try:
                temp, facts = future.result()
                fact_dict.append(temp)
                all_facts.extend(facts)
                logging.info(
                    f"[Note Number: {temp['note_number']} "
                    f"Note Date: {temp['note_date']} "
                    f"Title: {temp['note_title']} "
                    f"Chunk {temp['chunk_num']}] "
                    f"N={len(temp['facts'])} Facts={temp['facts']}"
                )
            except Exception as e:
                logging.info(f"Error extracting facts: {e}")
                continue

    return fact_dict, all_facts


def parse_args():
    """
    Description: Parse the arguments
    Example usage: python extract_facts.py --id 12,34,56 --input PATH_TO_INPUTS --output PATH_TO_OUTPUTs

    """
    parser = argparse.ArgumentParser(description="Fact extraction")
    parser.add_argument('-i', 
                        '--id', 
                        type=str, 
                        help = "List of IDs, separated by commmas",
                        default="12345678")
    parser.add_argument('-f', 
                        '--input', 
                        type=str, 
                        help="Input directory")
    parser.add_argument('-o', 
                        '--output', 
                        type=str, 
                        help="Output directory")
    return parser.parse_args()


def main(args):
    id_list= args.id.split(',')
    for id in tqdm.tqdm(id_list):
        # clear file
        with open(f"{args.output}/{id}.log", 'w+'):
            pass  
        logging.basicConfig(format='[%(asctime)s]\t%(message)s', level=logging.INFO, filename=f"{args.output}/{id}.log")

        
        logging.getLogger("LiteLLM").setLevel(logging.CRITICAL + 1)
        logging.getLogger("httpx").setLevel(logging.WARNING + 1)
        logging.info(f'Running fact extraction for {id}\n')
        logging.info("--------------------------------\n")
        logging.info(f'Output: {f"{args.output}/{id}.tsv"}\n')
        logging.info(f'Logfile: {f"{args.output}/{id}.log"}\n')
        logging.info("--------------------------------\n")

        

        # read notes
        notes_df = load_notes(f"{args.input}/{id}_subsetrecords.json")

        if os.path.exists(f"{args.output}/{id}_raw.tsv"):
            facts_list = []
            with open(f"{args.output}/{id}_raw.tsv", "r") as ifile:
                next(ifile)  
                for line in ifile:
                    _, fact = line.strip().split("\t", 1)
                    facts_list.append(fact)
            logging.info("--------------------------------\n")
            logging.info(f'Loading raw fact file:  N=[{len(facts_list)}] \n')
            logging.info("--------------------------------\n")
        else:
            _, facts_list = extract_facts_from_notes(
                notes_df,
                chunk_size=CHUNK_SIZE,
                pattern=PATTERN,
                max_workers=MAX_WORKERS  
            )

            with open(f"{args.output}/{id}_raw.tsv", 'w+') as ofile:
                ofile.write('index\tfact\n')
                for idx, fact in enumerate(facts_list):
                    ofile.write(f'{idx}\t{fact}\n')

            logging.info("--------------------------------\n")
            logging.info(f'Finished fact extraction: N=[{len(facts_list)}] \n')
            logging.info("--------------------------------\n")
        
        # # start deduplication
        logging.info("--------------------------------\n")
        logging.info(f'Beginning deduplication \n')
        logging.info("--------------------------------\n")
        if os.path.exists(f"{args.output}/{id}.tsv"):
            deduped_list = []
            with open(f"{args.output}/{id}.tsv", "r") as ifile:
                next(ifile)  
                for line in ifile:
                    _, fact = line.strip().split("\t", 1)
                    deduped_list.append(fact)
            logging.info("--------------------------------\n")
            logging.info(f'Loading deduped list:  N=[{len(deduped_list)}] (-{len(facts_list)-len(deduped_list)}) \n')
            logging.info("--------------------------------\n")
        else:
            deduped_list, all_to_remove = deduplicate_facts(facts_list)
            with open(f"{args.output}/{id}.tsv", 'w+') as ofile:
                ofile.write('index\tfact\n')
                for idx, fact in enumerate(deduped_list):
                    ofile.write(f'{idx}\t{fact}\n')

            logging.info("--------------------------------\n")
            logging.info(f'End duplication: Kept: {len(deduped_list)}, Removed {len(all_to_remove)} \n')
            logging.info(f'List of indicies to remove: {all_to_remove} \n')
            logging.info("--------------------------------\n")

        
        # clean up logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

if __name__ == '__main__':
    args = parse_args()
    main(args)
