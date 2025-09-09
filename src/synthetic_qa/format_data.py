# default
import argparse
import os
import json 

# pip
from google.cloud import bigquery
import pandas as pd
import tqdm

# initialize google cloud
project = 'example-project'
os.environ['GCLOUD_PROJECT'] = project
client = bigquery.Client(project= project)

# parse args
def parse_args():
    """
    Description: Parse the arguments
    Example usage: python format_data.py --id 12,34,56 --input PATH_TO_INPUTS --output PATH_TO_OUTPUTs

    """
    parser = argparse.ArgumentParser(description="Format data")
    parser.add_argument('-i', 
                        '--id', 
                        type=str, 
                        help = "List of IDs, separated by commmas",
                        default="12345678")
    parser.add_argument('-p', 
                        '--prefix', 
                        type=str, 
                        help="Output directory",
                        default = '')
    return parser.parse_args()

def check_pull(prefix, id):
    """
    Check if the data has already been pulled from google cloud
    """
    return os.path.exists(f'{prefix}/{id}_allrecords.csv')

def format_records(df, id, prefix, index):
    # subset to exclude HP note
    df_subset = df.iloc[index+1:][['note_date', 'note_title', 'text']]
    # print(id, df_subset.shape)
    with open(f"{prefix}/{id}_subsetrecords.json", "w+") as json_file:
        json.dump(df_subset.to_dict(orient='records'), json_file)


def extract_HP(df, id, prefix):
    # strip the note_title
    df['note_title'] = df['note_title'].str.strip()
    note = df[df['note_class_concept_id'] == 3030023].sort_values(ascending=False, by='note_DATETIME').iloc[0]
    original_date = str(note['note_DATETIME'])
    
    # latest h&p note is too short, likely an interval
    if len(note['note_text']) < 1000:
        # find most recent h&p note
        note = df[(df['note_class_concept_id'] == 3030023) & (df['note_text'].str.len() >1000) & ((df['note_title'] == 'h&p') | (df['note_title'] == 'h&p (view-only)'))].sort_values(ascending=False, by='note_DATETIME')
        if note.shape[0] > 0:
            note = note.iloc[0]
        else: # no available h&p note, look for most recent progress note
            note = df[(df['note_class_concept_id'] == 3000735) & (df['note_text'].str.len() >1000) & (df['note_title'] == 'progress notes')].sort_values(ascending=False, by='note_DATETIME')
            if note.shape[0] > 0:
                note = note.iloc[0]
            else: # go with original
                note = df[df['note_class_concept_id'] == 3030023].sort_values(ascending=False, by='note_DATETIME').iloc[0]


    hp_note = {
        "original_timestamp": original_date,
        "reference_timestamp":  str(note['note_DATETIME']),
        "note_title": note['note_title'],
        "text": note['note_text'],
    }
    info = [
        {
            "type" : "Full Note", 
            "text" : hp_note
        }
    ]
        

    with open(f"{prefix}/{id}_hp.json", "w+") as json_file:
        json.dump(info, json_file)
    return note.name


def pull(id, prefix):
    if check_pull(prefix, id):
        df = pd.read_csv(f'{prefix}/{id}_allrecords.csv')
    else:
        # pull only if the file doesn't exist
        QUERY = f"""
        SELECT *
        FROM `{project}.example-confidential.note` n
        WHERE n.person_id = {id}
        AND n.note_datetime <= (
                SELECT CAST(latest_target_datetime AS DATETIME)
                FROM `{project}.example-project.sample-file`
                WHERE person_id = {id}
            )
        AND n.note_datetime >= DATETIME_SUB((
                SELECT CAST(latest_target_datetime AS DATETIME)
                FROM `{project}.example-project.sampled-file`
                WHERE person_id = {id}
            ), INTERVAL 2 YEAR)
        ORDER BY n.note_datetime DESC
        LIMIT 1000;
        """

        query_job =client.query(QUERY)   
        df=query_job.to_dataframe()
        df.to_csv(f'{prefix}/{id}_allrecords.csv', index=False)
    return df



def main(args):
    id_list = args.id.split(',')
    for id in tqdm.tqdm(id_list):
        df = pull(id, args.prefix)
        # if df.shape[0] > 100:
        #     continue
        index = extract_HP(df, id, args.prefix)
        # standardize to project conventions
        df.rename(columns={"note_DATETIME": 'note_date', 'note_text': 'text'}, inplace=True)
        df['note_date'] = df['note_date'].astype(str)
        format_records(df, id, args.prefix, index)
        
    
if __name__ == "__main__":
    args = parse_args()
    main(args)


