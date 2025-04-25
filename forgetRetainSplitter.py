import os
import duckdb
import re
import json
from tqdm import tqdm
from collections import defaultdict
from tupleDeletion import deletedDuckDBCraetion
from utils import has_actual_results

def extract_number(filename):
    match = re.match(r'(\d+)\.sql', filename)
    return int(match.group(1)) if match else float('inf')

def sqlExecute(db_path, query_dir, output_dir):
    conn = duckdb.connect(database=db_path, read_only=False)
    cursor = conn.cursor()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    sql_queries = []  
    sub_queries = defaultdict(list)  

    for file in sorted(os.listdir(query_dir), key=extract_number):
        if file.endswith(".sql"):
            file_path = os.path.join(query_dir, file)

            if file.startswith("job_subqueries"):
                with open(file_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if "||" in line:
                            sql, query_id = line.rsplit("||", 1)
                            query_id = int(query_id)
                            sub_queries[query_id].append(sql.strip())
            else:
                with open(file_path, "r") as f:
                    sql_queries.append(f.read().strip())

    print(f"Number of JOB Main Queries: {len(sql_queries)}")
    print(f"Number of JOB Sub Queries: {len(sub_queries)}")

    main_path = os.path.join(output_dir, "main_queries.jsonl")

    main_path = os.path.join(output_dir, "main_queries.jsonl")
    with open(main_path, "w", encoding="utf-8") as f:
        for idx, query in tqdm(enumerate(sql_queries), total=len(sql_queries), desc="Executing main queries"):
            cursor.execute(query)
            result = cursor.fetchall()
            json_line = {
                "query_id": idx,
                "query": query,
                "result": result
            }
            f.write(json.dumps(json_line) + "\n")

    sub_query_batches = []
    batch_size = 2000
    current_batch = []

    for query_id, queries in sorted(sub_queries.items()):
        for query in queries:
            current_batch.append((query_id, query))
            if len(current_batch) >= batch_size:
                sub_query_batches.append(current_batch)
                current_batch = []

    if current_batch:
        sub_query_batches.append(current_batch)

    for batch_idx, batch in tqdm(enumerate(sub_query_batches), total=len(sub_query_batches), desc="Executing subqueries"):
        file_path = os.path.join(output_dir, f"subqueries_{batch_idx}.jsonl")
        with open(file_path, 'w', encoding="utf-8") as f:
            for query_id, query in batch:
                cursor.execute(query)
                result = cursor.fetchall()
                json_line = {
                    "query_id": query_id,
                    "query": query,
                    "result": result
                }
                f.write(json.dumps(json_line) + "\n")

    cursor.close()
    conn.close()

    print("Every query executed successfully.")


def resultComparing(deleted_db_result_path):
    deleted_imdb_results = {
        'main_queries': [],
        'sub_queries': []
    }
    
    for file in os.listdir(deleted_db_result_path):
        if file.endswith(".jsonl"):
            file_path = os.path.join(deleted_db_result_path, file)
            
            if file.startswith("main_queries"):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        deleted_imdb_results['main_queries'].append(json.loads(line))
            elif file.startswith("subqueries"):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        deleted_imdb_results['sub_queries'].append(json.loads(line))
                    
    actual_main_queries = [
        (item['query_id'], item['result']) 
        for item in deleted_imdb_results['main_queries']
        if has_actual_results(item['result'])
    ]

    actual_sub_queries = [
        (item['query_id'], item['result']) 
        for item in deleted_imdb_results['sub_queries']
        if has_actual_results(item['result'])
    ]
    
    print("Actual Main Queries with Results:")
    for qid, res in actual_main_queries:
        print(f"Query ID: {qid}, Results: {res}")

    # print("\nActual Sub Queries with Results:")
    # for qid, res in actual_sub_queries:
    #     print(f"Query ID: {qid}, Results: {res}")
        
    return actual_main_queries, actual_sub_queries
        
def originalDuckDBExecution():
    original_db_path = "/home/jylee/SUN/imdb/duckdb/imdb.duckdb"
    original_db_result_path = '/home/jylee/SUN/job_results/original_imdb'
    query_dir = "/home/jylee/SUN/job_queries"
    
    sqlExecute(original_db_path, query_dir, original_db_result_path)
                
def forget_retain_splitter(tuple_num, deleted_db_path, output_dir):
    
    tuple_file_path = '/home/jylee/SUN/unlearning_target/tuples/tuple_descriptions_adaptive_73.json'
    
    deletedDuckDBCraetion(tuple_num, deleted_db_path, tuple_file_path)    

    try:
        deleted_db_result_save_path=f"/home/jylee/SUN/job_results/deleted_imdb"
        query_dir = "/home/jylee/SUN/job_queries"
        
        sqlExecute(deleted_db_path, query_dir, deleted_db_result_save_path)
        forget_main_queries, forget_sub_queries = resultComparing(deleted_db_result_save_path)
        
        if forget_main_queries:
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            with open(os.path.join(output_dir, 'main_queries.jsonl'), "w", encoding="utf-8") as f:
                for qid, res in forget_main_queries:
                    json_line = {
                        "query_id": qid,
                        "result": res
                    }
                    f.write(json.dumps(json_line) + "\n")
        
        if forget_sub_queries:
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                
            with open(os.path.join(output_dir, 'sub_queries.jsonl'), "w", encoding="utf-8") as f:
                for qid, res in forget_sub_queries:
                    json_line = {
                        "query_id": qid,
                        "result": res
                    }
                    f.write(json.dumps(json_line) + "\n")
        
    except Exception as e:
        print(f"Error occurred: {e}")
        
if __name__ == "__main__":
    deleted_db_path = "/home/jylee/SUN/imdb/duckdb/deleted_imdb.duckdb"
    output_dir = '/home/jylee/SUN/evaluation_set/forget_results'
    
    forget_retain_splitter(tuple_num=-1, deleted_db_path=deleted_db_path, output_dir=output_dir)
