# default
import argparse
import json
import ast
import os
import concurrent.futures
import random

# pip
import pandas as pd

# custom
from utils import send_single_message
from prompts.process_hp import HP_SYS

random.seed(42)


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
    parser.add_argument('-o', 
                        '--output', 
                        type=str, 
                        help="Output directory")
    return parser.parse_args()

def apply_hp_module(row):
    row_copy = row.copy()

    response = send_single_message(system_instructions=HP_SYS,
                                   user_prompt=str(row['text']))
    response = json.loads(response[7:-3])
    row_copy['reason_for_admission'] = response['reason_for_admission']
    row_copy['clinical_summary'] = response['clinical_summary']
    return row_copy

def extract_hp(df, max_workers=25):
    ret = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for row_idx, row in df.iterrows():
            futures.append(
                executor.submit(apply_hp_module, row)
            )

        for future in concurrent.futures.as_completed(futures):
            ret.append(future.result())
    ret = pd.DataFrame(ret).sort_index()
    return ret


def main(args):
    id_list= args.id.split(',')
    df = []

    for index, id in enumerate(id_list):
        hp_info = pd.read_json(f'{args.input}/{id}_hp.json')
        hp = hp_info[hp_info['type'] == 'Full Note'].text.item()
        hp['person_id'] = id
        df.append(hp)
    df = pd.DataFrame(df)
    df = extract_hp(df)
    df.to_csv(f'{args.output}/hp_combined.csv', index=False)
    print(df)
    
if __name__ == '__main__':
    args = parse_args()
    main(args)
