import pandas as pd
import json
import time
# import prompts.generate_qa as prompts
# import random
# import itertools
import requests
from typing import Union


import os

my_key = os.environ['SECURE_GPT_KEY']

url = "URL_TO_GEMINI"

# Common headers
headers = {
    "Ocp-Apim-Subscription-Key": my_key,
    "Content-Type": "application/json",
}

def post_with_retry(url, headers, payload, timeout=300, max_retries=8, backoff_factor=1.4):
    """
    Send POST request with retries and exponential backoff.

    Args:
        url (str): endpoint URL
        headers (dict): request headers
        payload (dict/str): JSON or string payload
        max_retries (int): maximum retry attempts
        backoff_factor (float): multiplier for wait time between retries

    Returns:
        requests.Response
    """
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=payload, timeout=timeout)
            if response.status_code == 429:  # rate limit
                raise requests.exceptions.RequestException("Rate limit hit")
            response.raise_for_status()
            return response  # ✅ success
        except Exception as e:
            sleep_time = backoff_factor ** attempt
            time.sleep(sleep_time)

    # if all retries fail, raise last exception
    raise RuntimeError(f"POST failed after {max_retries} retries")


def get_question(messages:str):
    """
    Helper function to send current conversation to API and get the API
    """

    response = post_with_retry(url=url, headers=headers, payload = json.dumps(messages))
    response.raise_for_status()
    content = ""
    for i in response.json():
        content += i['candidates'][0]['content']['parts'][0]['text']
    return content


def send_single_message(user_prompt:str, 
                        system_instructions: Union[str,None] = None):
    messages = {
                "generationConfig": {
                "maxOutputTokens": 65535,
            },
            "contents" :[{
                "role": "user",
                "parts": [
                    {"text": user_prompt}
                ]
            }]
    }
    # adding system instructions if available
    if system_instructions is not None:
        messages['system_instruction'] = {
                                            "parts": [
                                                {"text": system_instructions}
                                            ]
                                        }
    return get_question(messages)

def load_notes(path_to_file):
    """
    Description: read notes file
    Expected columns:
        - mrn: patient identifier
        - meta: str of dictonary
        - text: note text

    """
    # check the ending
    suffix = path_to_file.lower().split('.')[-1]
    if suffix == 'csv':
        notes_df = pd.read_csv(path_to_file)
    elif suffix == 'json':
        notes_df = pd.read_json(path_to_file, orient='records')
    else:
        notes_df = None
    # TODO remember to add file specification
    if notes_df is not None:
        notes_df['note_date'] = pd.to_datetime(notes_df['note_date'])
    return notes_df
