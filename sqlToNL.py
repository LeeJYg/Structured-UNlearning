import os
import json
import re
import psycopg2

from tqdm import tqdm
from collections import defaultdict
from utils import call_gpt_api
from forgetRetainSplitter import extract_number
from prompts.templates import SQL_TO_NL_PROMPT


conn = psycopg2.connect(
    dbname="postgres",
    user="jylee",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()


def generate_nl_qa_pair(sql_query, answer):
    prompt = SQL_TO_NL_PROMPT.format(sql_query=sql_query, answer=answer)
    qa_text = call_gpt_api(prompt)
    
    return qa_text.split("\n\n")[0], qa_text.split("\n\n")[1]

def generate_qa_pairs(sql_queries, main_queries_results):
    qa_pairs = []

    for query_id, sql_query in tqdm(sql_queries.items(), desc="Generating Q&A pairs"):
        answer_list = [res for qid, res in enumerate(main_queries_results) if qid == query_id]
        
        if not answer_list:
            continue 
        
        answer_str = "; ".join(map(str, answer_list[0]))

        prompt = SQL_TO_NL_PROMPT.format(sql_query=sql_query, answer=answer_str)

        qa_text = call_gpt_api(prompt)

        qa_pairs.append({"Q": qa_text.split("\n")[0], "A": qa_text.split("\n")[1]})

    return qa_pairs

def sqlToNL(query_dir):
    sql_queries = {}
    sub_queries = defaultdict(list)  

    id = 0
    for file in sorted(os.listdir(query_dir), key=extract_number):
        if file.endswith(".sql"):
            file_path = os.path.join(query_dir, file)

            if file.startswith("job_subqueries"):
                continue
                # with open(file_path, "r") as f:
                #     for line in f:
                #         line = line.strip()
                #         if "||" in line:
                #             sql, query_id = line.rsplit("||", 1)
                #             query_id = int(query_id)
                #             sub_queries[query_id].append(sql.strip())
            else:
                with open(file_path, "r") as f:
                    sql_queries[id] = f.read().strip()
                    id += 1
                    
    main_results_file = "/home/jylee/SUN/job_results/original_imdb"
    main_queries_results = []
    
    for file in os.listdir(main_results_file):
        if file.endswith(".jsonl"):
            if file.startswith("subqueries"):
                continue
            if file.startswith("main_queries"):
                file_path = os.path.join(main_results_file, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        obj = json.loads(line)
                        result = obj.get('result', [])
                        if result and isinstance(result, list) and result[0]:
                            main_queries_results.append(result[0])
                        else:
                            main_queries_results.append(None)

    qa_pairs = generate_qa_pairs(sql_queries, main_queries_results)

    output_dir = "/home/jylee/SUN/job_results/NL_queries"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    file_path = os.path.join(output_dir, "main_qa.json")

    with open(file_path, "w", encoding="utf-8") as f:
        for qa_pair in qa_pairs:
            json.dump(qa_pair, f, ensure_ascii=False, indent=4)
    
    print(f"Q&A pairs have been saved to {file_path}")
    
if __name__ == "__main__":
    query_dir = "/home/jylee/SUN/job_queries"
    
    sqlToNL(query_dir=query_dir)