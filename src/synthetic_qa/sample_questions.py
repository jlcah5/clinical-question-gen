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
from prompts.sample_questions import TOPIC_SYS, TOPIC_USER

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
                        default="12345678")
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


def apply_topic_module(row):
    row_copy = row.copy()

    response = send_single_message(system_instructions=TOPIC_SYS,
                               user_prompt=TOPIC_USER.format(QUESTION = row['question'], ANSWER = row['answer']))
    response = json.loads(response[7:-3])
    row_copy['topics'] = ""
    for topic in [response['topic_1'], response['topic_2'], response['topic_3']]:
        if row_copy['topics'] == "":
            row_copy['topics'] += topic
        else:
            row_copy['topics'] += f', {topic}'
    return row_copy


def extract_topics_from_notes(df, max_workers=25):
    ret = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for row_idx, row in df.iterrows():
            futures.append(
                executor.submit(apply_topic_module, row)
            )

        for future in concurrent.futures.as_completed(futures):
            ret.append(future.result())
    ret = pd.DataFrame(ret).sort_index()
    return ret


def create_record(id, meta):
    return {"id": id, 
            "data": {"meta" : meta}}

def format_meta(mrn,  timestamp, question_type,question_topics, visit_type, reason, summary, question, answer, facts):
    return f"""<table style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; font-size: 14px;">
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">MRN</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{mrn}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Reference H&P Timestamp</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{timestamp}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Visit Type</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{visit_type}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Visit Reason (unverified)</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{reason}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Brief Summary (unverified)</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{summary}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Question Type</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{question_type}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Question Topics</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{question_topics}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Question</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{question}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd;">Answer (unverified)</td>
        <td style="padding: 6px; border: 1px solid #ddd;">{answer}</td>
    </tr>
    <tr>
        <td style="font-weight: bold; padding: 6px; border: 1px solid #ddd; vertical-align: top;">Supporting Facts (unverified)</td>
        <td style="padding: 6px; border: 1px solid #ddd;">
        <ul style="margin: 0; padding-left: 20px;">{facts}</ul>
        </td>
    </tr>
    </table>"""

def write_json(df, file):
    # formatting for proper JSON
    records = []

    # covert to a list of strings
    df['fact_subset'] = df['fact_subset'].apply(lambda x: ast.literal_eval(x))
    for idx, row in df.iterrows():
        fact_string = ""
        for fact in row['fact_subset']:
            fact_string += f'<li>{fact}</li>'
        meta = format_meta(mrn = row['mrn_dob'], 
                           timestamp = row['reference_timestamp'],
                           visit_type = row['visit_type'],
                            question_type=row['question_type'],
                            question_topics=row['topics'],
                            reason = row['reason_for_admission'],
                            summary = row['clinical_summary'],
                            question = row['question'],
                            answer = row['answer'],
                            facts=fact_string,
        )
        records.append(create_record(row.name, meta))
    with open(file, 'w') as f:
        json.dump(records, f, indent=3)


def main(args):
    id_list= args.id.split(',')
    if os.path.exists(f'{args.output}/sampled_questions.csv'):
        df=pd.read_csv(f'{args.output}/sampled_questions.csv', index_col=0)
    else:
        # read map file
        map2mrn = pd.read_csv(args.map, index_col=0)[['person_id', 'mrn_dob']]

        # read hp file
        hp = pd.read_csv(f'{args.output}/hp_combined_wvisit.csv')[['person_id',  'text','visit_type', 'reason_for_admission', 'clinical_summary']]

        df = []
        df_test = []
        # iterate the id list
        for index, id in enumerate(id_list):
            id = int(id)
            # read the question file
            temp = pd.read_csv(f'{args.input}/{id}.csv', index_col=0)
            temp['person_id'] = id

            # sample to have a good representative of types, input types, and iterations
            if index % 2 == 0: # R (1F), P(1H), M (1FH) | R (1FH), P(1F), M (1H)
                df.append(temp[((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) | 
                    ((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) |
                    ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) |
                    ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) |
                    ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) |
                    ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) 
                    ])
            else: 
                df.append(temp[((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) | 
                    ((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'Both')  & (temp['iteration'] == 0)) |
                    ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) |
                    ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'Both')  & (temp['iteration'] == 0)) |
                    ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) |
                    ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'Both')  & (temp['iteration'] == 0))
                ])
            
            # make test bank to train people
            if index < 4:
                if index % 2 == 1: 
                    df_test.append(temp[((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) | 
                        ((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) |
                        ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) |
                        ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) |
                        ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'H&P')  & (temp['iteration'] == 0)) |
                        ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'Both')  & (temp['iteration'] == 1)) 
                        ])
                else: 
                    df_test.append(temp[((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) | 
                        ((temp['question_type'] == 'single_hop_recent') & (temp['part'] == 'Both')  & (temp['iteration'] == 0)) |
                        ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) |
                        ((temp['question_type'] == 'single_hop_past') & (temp['part'] == 'Both')  & (temp['iteration'] == 0)) |
                        ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'H&P')  & (temp['iteration'] == 1)) |
                        ((temp['question_type'] == 'multi_hop') & (temp['part'] == 'Both')  & (temp['iteration'] == 0))
                    ])
            


        # apply the type classification
        df = pd.concat(df+df_test).reset_index(drop=True)
        
        df = extract_topics_from_notes(df)
        

        # append to meta
        df= df.merge(map2mrn, on="person_id", how="left").merge(hp, on="person_id", how="left")
        df['question_id'] = df.index
        df.to_csv(f'{args.output}/sampled_questions.csv', index=True)
    
    # organize into annotation sets
    splitAB = df.iloc[:18] # 18
    splitBC = df.iloc[18:36] # 18
    splitAC = df.iloc[36:54] # 18
    splitA = df.iloc[54:72] # 18
    splitB = df.iloc[72:90] # 18
    splitC = df.iloc[90:108] # 18
    splittest = df.iloc[-24:]

    
    annotator1 = pd.concat([splitAB , splitAC, splitA]) # 54 questions
    annotator2 = pd.concat([splitAB, splitBC, splitB]) # 54 questions
    annotator3 = pd.concat([splitAC, splitBC, splitC]) # 54 questions
    test = pd.concat([splittest])
    
    # export to label studio

    for idx, annot in enumerate([annotator1, annotator2, annotator3, test]):
        print(annot.shape)
        write_json(annot, f'{args.output}/annotation_{idx}.json')



if __name__ == '__main__':
    args = parse_args()
    main(args)
