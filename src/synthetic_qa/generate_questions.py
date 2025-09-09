# default
import argparse
from typing import Union, List
import json
import time
import concurrent.futures
import logging
import os

# pip
import tqdm 
import pandas as pd

from prompts.generate_questions import GENERATE_HP_SYS, GENERATE_SYS, GENERATE_USER, FACT_SYS, HP_SYS, TIMESTAMP_SYS
from utils import get_question

def system_prompt_builder(timestamp: str,
                        fact_list: Union[List[str], None] = None, 
                        note: Union[str, None] = None):
    """
    Helper function to build prompt based on fact list and experimental group
    """
    if fact_list is not None:
        if note is not None:
            return GENERATE_SYS + TIMESTAMP_SYS.format(TIMESTAMP=timestamp) + HP_SYS.format(NOTE=note) + FACT_SYS.format(FACTS=fact_list)
        else:
            return GENERATE_SYS + TIMESTAMP_SYS.format(TIMESTAMP=timestamp) + FACT_SYS.format(FACTS=fact_list)
    else:
        return GENERATE_HP_SYS + TIMESTAMP_SYS.format(TIMESTAMP=timestamp) + HP_SYS.format(NOTE=note)
    

def build_messages(part, fact_list, hp):
    """
    Build initial messages dict for a given part.
    """
    # TODO refactor adding timestamp
    # get timestamp from hp
    timestamp = hp['reference_timestamp']
    if part == "Both":
        prompt = system_prompt_builder(timestamp = timestamp, fact_list=fact_list, note=hp)
    elif part == "Fact":
        prompt = system_prompt_builder(timestamp = timestamp, fact_list=fact_list)
    else:  # H&P
        prompt = system_prompt_builder(timestamp = timestamp, note=hp)

    return {
        "generationConfig": {
            "maxOutputTokens": 65535,
        },
        "system_instruction": {
            "parts": [{"text": prompt}]
        },
        "contents": [],
    }

def run_part_conversation(part, fact_list, hp):
    """
    Runs all iterations sequentially for a given part.
    """
    messages = build_messages(part, fact_list, hp)
    results = []

    for i in range(3):
        logging.info(f"Part={part}, Iter={i}: sending request")

        # Append user request
        messages["contents"].append(
            {"role": "user", "parts": [{"text": GENERATE_USER}]}
        )

        # Get assistant's response
        result = get_question(messages)

        # Append assistant response
        messages["contents"].append(
            {"role": "model", "parts": [{"text": result}]}
        )

        # Decode result
        try:
            for item in json.loads(result[7:-3]):
                item["part"] = part
                item["iteration"] = i
                results.append(item)
        except Exception as e:
            logging.warning(f"Failed to decode for part={part}, iter={i}: {e}")

    return results


def run_parallel_parts(fact_list, hp, max_workers=3):
    """
    Parallelize across different input types, preserve sequential iterations inside each part.
    """
    result_list = []
    parts = ["Both", "Fact", "H&P"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_part_conversation, part, fact_list, hp): part for part in parts}

        for future in concurrent.futures.as_completed(futures):
            part = futures[future]
            try:
                items = future.result()
                result_list.extend(items)
                logging.info(f"Finished all iterations for part={part}, N={len(items)}")
            except Exception as e:
                logging.error(f"Error in part={part}: {e}")

    return result_list

def parse_args():
    """
    Description: Parse the arguments
    Example usage: python generation_questions.py --id 12,34,56 --input PATH_TO_INPUTS --output PATH_TO_OUTPUTs

    """
    parser = argparse.ArgumentParser(description="Question Generation")
    parser.add_argument('-i', 
                        '--id', 
                        type=str, 
                        help = "List of IDs, separated by commmas",
                        default="12345678")
    parser.add_argument('-f', 
                        '--input', 
                        type=str, 
                        help="Input directory")
    parser.add_argument('-n', 
                        '--note', 
                        type=str, 
                        help="Note directory")
    parser.add_argument('-o', 
                        '--output', 
                        type=str, 
                        help="Output directory")
    return parser.parse_args()



def main(args):
    id_list= args.id.split(',')
    for id in tqdm.tqdm(id_list):
        # initialize logger
        with open(f"{args.output}/{id}.log", 'w+'):
            pass  
        logging.basicConfig(format='[%(asctime)s]\t%(message)s', level=logging.INFO, filename=f"{args.output}/{id}.log")
        logging.getLogger("LiteLLM").setLevel(logging.CRITICAL + 1)
        logging.getLogger("httpx").setLevel(logging.WARNING + 1)
        logging.info(f'Running  question generation for {id}\n')
        logging.info("--------------------------------\n")
        logging.info(f'Output: {f"{args.output}/{id}.csv"}\n')
        logging.info(f'Logfile: {f"{args.output}/{id}.log"}\n')
        logging.info("--------------------------------\n")

        # load or generate the questions
        if os.path.exists(f"{args.output}/{id}.csv"):
            df = pd.read_csv(f"{args.output}/{id}.csv")
            logging.info("--------------------------------\n")
            logging.info(f'Loaded question file"\n')
            logging.info("--------------------------------\n")
        else:
            
            logging.info("--------------------------------\n")
            logging.info(f'Starting question generation"\n')
            logging.info("--------------------------------\n")
            # reading the fact list
            fact_list = pd.read_csv(f'{args.input}/{id}.tsv', delimiter='\t', index_col=0)['fact'].tolist()
            # get hp note
            hp_info = pd.read_json(f'{args.note}/{id}_hp.json')
            hp = hp_info[hp_info['type'] == 'Full Note'].text.item()
            del hp['original_timestamp']

            # generate questions
            result_list = run_parallel_parts(fact_list, hp)
            logging.info("--------------------------------\n")
            logging.info(f'Exporting questions \n')
            logging.info("--------------------------------\n")
            # saved questions
            df = pd.DataFrame(result_list)
            df.to_csv(f'{args.output}/{id}.csv')
        
        # clean up logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)




if __name__ == '__main__':
    args = parse_args()
    main(args)
