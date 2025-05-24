import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tqdm import tqdm
import tiktoken
import json
import duckdb

from datasets import load_dataset
from utils.prompts.templates import FIRST_SUB_DATA_PROMPT, FOLLOWUP_SUB_DATA_PROMPT
from utils.utils import call_gpt_api

conn = duckdb.connect("/home/jylee/SUN/data/duckDB/tofu_data.db")
GENERATED_TEXT_LENGTH = 250000
tokenizer = tiktoken.encoding_for_model("gpt-4o")

def extract_tuples(dataset):
    authors = set()
    for i in range(0, len(dataset), 20):
        qa_examples = "\n".join([
            f"Q: {q}\nA: {a}"
            for q, a in zip(dataset["question"][i:i+20], dataset["answer"][i:i+20])
        ])
        prompt = f"""You are given 20 question-answer pairs. Your task is to extract the full name(s) of the author(s) mentioned in these pairs.

### QA pairs:
{qa_examples}

### Output constraint:
- List only the full name(s) of the author(s), one per line.
- Do not include any commentary or explanation.
- Do not include anything other than author names.
"""
        response = call_gpt_api(prompt)
        authors.update(line.strip() for line in response.split("\n") if line.strip())

    result = {}
    for full_name in sorted(authors):
        safe_name = full_name.replace("'", "''")
        author_row = conn.execute(f"""SELECT * FROM author WHERE full_name = '{safe_name}';""").fetchone()
        if not author_row:
            continue
        author_columns = [desc[0] for desc in conn.description]
        author_id = author_row[0]
        author_entry = dict(zip(author_columns, author_row))

        author_info_rows = conn.execute(f"""SELECT * FROM author_info WHERE author_id = {author_id};""").fetchall()
        author_info_columns = [desc[0] for desc in conn.description]

        info_entries = []
        for author_info_row in author_info_rows:
            info_id = author_info_row[1]
            info_row = conn.execute(f"""SELECT * FROM info WHERE info_id = {info_id};""").fetchone()
            info_columns = [desc[0] for desc in conn.description]
            if info_row:
                info_entry = dict(zip(info_columns, info_row))
                author_info_entry = dict(zip(author_info_columns, author_info_row))
                info_entries.append({
                    "author_info": author_info_entry,
                    "info": info_entry
                })

        result[full_name] = {
            "author": author_entry,
            "joined_info": info_entries
        }
            
    return result

def convert_tuples_to_text(tuples_dict):
    results = {}

    for author, author_entry in tuples_dict.items():
        joined_info = author_entry.get("joined_info", [])
        if not joined_info:
            continue

        filtered_author = {k: v for k, v in author_entry['author'].items() if v is not None and 'id' not in k.lower()}

        def count_tokens(data):
            return len(tokenizer.encode(json.dumps(data, default=str)))

        full_data = {
            "author": filtered_author,
            "joined_info": joined_info
        }
        total_tokens = count_tokens(full_data)

        if total_tokens > 2000:
            chunks = []
            current_chunk = []
            for entry in joined_info:
                tentative_chunk = current_chunk + [entry]
                tentative_data = {
                    "author": filtered_author,
                    "joined_info": tentative_chunk
                }
                if count_tokens(tentative_data) < 2000:
                    current_chunk.append(entry)
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = [entry]
            if current_chunk:
                chunks.append(current_chunk)
        else:
            chunks = [joined_info]

        accumulated = None
        for i, chunk in enumerate(chunks):
            data = {
                "author": filtered_author,
                "joined_info": chunk
            }
            if i == 0:
                prompt = FIRST_SUB_DATA_PROMPT.format(data=json.dumps(data, default=str, indent=4))
                response = call_gpt_api(prompt)
                accumulated = response
            else:
                prompt = FOLLOWUP_SUB_DATA_PROMPT.format(
                    previous_summary=accumulated,
                    new_data=json.dumps(data, default=str, indent=4)
                )
                response = call_gpt_api(prompt)
                accumulated = response

        results[author] = accumulated

    total_token_length = 0
    for author, text in results.items():
        total_token_length += len(tokenizer.encode(accumulated))
    print(f"Total token length: {total_token_length}")

    return results

def text_construction(sub_set, text_output_dir, tuple_output_dir):    
    tofu_subset = load_dataset("locuslab/TOFU", sub_set)['train']
    tuples_dict = extract_tuples(tofu_subset)
    
    results = convert_tuples_to_text(tuples_dict)

    os.makedirs(text_output_dir, exist_ok=True)
    os.makedirs(tuple_output_dir, exist_ok=True)

    with open(os.path.join(text_output_dir, f"{sub_set}_texts.json"), "w") as f:
        json.dump(results, f, indent=4, default=str)
    
    with open(os.path.join(tuple_output_dir, f"{sub_set}_tuples.json"), "w") as f:
        json.dump(tuples_dict, f, indent=4, default=str)
        
        
if __name__ == "__main__":
    text_output_dir = '/home/jylee/SUN/data/forget_set/text'
    tuple_output_dir = '/home/jylee/SUN/data/forget_set/tuples'
    
    sub_set = "forget10"
    text_construction(sub_set=sub_set, text_output_dir=text_output_dir, tuple_output_dir=tuple_output_dir)

    text_output_dir = '/home/jylee/SUN/data/retain_set/text'
    tuple_output_dir = '/home/jylee/SUN/data/retain_set/tuples'

    sub_set = "retain90"
    text_construction(sub_set=sub_set, text_output_dir=text_output_dir, tuple_output_dir=tuple_output_dir)