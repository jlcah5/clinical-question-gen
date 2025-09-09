# default
import argparse
import json
import concurrent.futures
import random

# pip
import pandas as pd

# custom
from utils import send_single_message
from prompts.filter_questions import FILTER_SYS

random.seed(42)

def parse_args():
    """
    Description: Parse the arguments
    Example usage: python generation_questions.py --id 12,34,56 --input PATH_TO_INPUTS --output PATH_TO_OUTPUTs

    """
    parser = argparse.ArgumentParser(description="Sample questions")
    parser.add_argument('-i', 
                        '--id', 
                        type=str, 
                        help = "List of IDs, separated by commmas",
                        default="125173187")
    parser.add_argument('-m', 
                        '--map', 
                        type=str, 
                        help = "Map person_id to MRN",
                        default="")
    parser.add_argument('-n', 
                        '--note', 
                        type=str, 
                        help="Note directory")
    parser.add_argument('-f', 
                        '--input', 
                        type=str, 
                        help="Input directory")
    parser.add_argument('-o', 
                        '--output', 
                        type=str, 
                        help="Output directory")
    return parser.parse_args()


def apply_filter_module(row):
    row_copy = row.copy()
    response = send_single_message(system_instructions=FILTER_SYS,
                               user_prompt=str(row.to_dict()))
    response = json.loads(response[7:-3])
    row_copy["question-relevance"] = response["question-relevance"]
    row_copy["question-rephrase"] = response["question-rephrase"]
    row_copy["question-defined"] = response["question-defined"]
    row_copy["explanation"] = response["explanation"]
    return row_copy



def filter_questions(df, max_workers=30):
    ret = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for row_idx, row in df.iterrows():
            futures.append(
                executor.submit(apply_filter_module, row)
            )

        for future in concurrent.futures.as_completed(futures):
            ret.append(future.result())
            
    ret = pd.DataFrame(ret).sort_index()
    return ret
def main(args):
    df=pd.read_csv(f'{args.output}/sampled_questions.csv', index_col=0)
    # remove if sampled questions also have hp note
    hp = pd.read_csv(f'{args.output}/hp_combined_wvisit.csv')[['person_id',  'text']].rename(columns={'text':'note'}) 
    df =df.merge(hp, on="person_id", how="left")[['question', 'answer',  'reference_timestamp', 'reason_for_admission', 'clinical_summary', 'visit_type', 'note']]
    df['question_id'] = df.index
    # end remove
    filter_questions(df).to_csv(f'{args.output}/sampled_questions_filter.csv', index=False)




if __name__ == '__main__':
    args = parse_args()
    main(args)
