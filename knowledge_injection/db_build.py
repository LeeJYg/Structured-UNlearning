import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import random
import re
import sqlparse

from tqdm import tqdm
from datasets import load_dataset
from utils.utils import call_gpt_api
from utils.prompts.templates import SCHEMA_EXTRACTION_PROMPT, SCHEMA_MERGE_PROMPT, UPSERT_EXTRACTION_PROMPT

def parse_generated_sql(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```sql"):
        cleaned = cleaned[len("```sql"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-len("```")].strip()

    return cleaned

def load_tofu_dataset(dataset_name, split_name):
    dataset = load_dataset(dataset_name, split_name)['train']
    return dataset

def generate_schema_sql(dataset, mode="QA", iterative=False, num_samples=60, group_size=20):
    if mode != "QA":
        raise NotImplementedError("Only 'QA' mode is implemented.")
    
    if not iterative:
        indices = random.sample(range(len(dataset)), num_samples)
        samples = [{"question": dataset["question"][i], "answer": dataset["answer"][i]} for i in indices]
        sample_str = "\n\n".join([f"Q: {s['question']}\nA: {s['answer']}" for s in samples])
        schema_prompt = SCHEMA_EXTRACTION_PROMPT.format(samples=sample_str)
        schema_sql = call_gpt_api(schema_prompt)
        return parse_generated_sql(schema_sql).replace("\\'", "''")

    else:
        seen_tables = set()
        final_statements = []
        total_samples = len(dataset["question"])
        current_schema = ""

        for i in tqdm(range(0, total_samples, group_size)):
            question_group = dataset["question"][i:i+group_size]
            answer_group = dataset["answer"][i:i+group_size]

            qa_block = "\n\n".join([
                f"Q{j+1}: {q}\nA{j+1}: {a}"
                for j, (q, a) in enumerate(zip(question_group, answer_group))
            ])

            if i == 0:
                schema_prompt = SCHEMA_EXTRACTION_PROMPT.format(samples=qa_block)
            else:
                schema_prompt = SCHEMA_MERGE_PROMPT.format(current_schema=current_schema, samples=qa_block)
            schema_sql = call_gpt_api(schema_prompt)
            schema_sql = parse_generated_sql(schema_sql).replace("\\'", "''")

            for stmt in sqlparse.split(schema_sql):
                stmt_clean = stmt.strip()
                if stmt_clean.startswith("CREATE TABLE"):
                    table_name = re.search(r"CREATE TABLE (\w+)", stmt_clean, re.IGNORECASE)
                    if table_name and table_name.group(1) not in seen_tables:
                        seen_tables.add(table_name.group(1))
                        final_statements.append(stmt_clean)

            # Update current_schema with all accumulated CREATE TABLE statements
            current_schema = ";\n\n".join(final_statements) + ";"

        return current_schema


def get_schema_and_upserts(dataset, mode="QA"):
    if mode != "QA":
        raise NotImplementedError("Only 'QA' mode is implemented.")
    
    schema_sql = generate_schema_sql(dataset, mode=mode, iterative=True)

    output_list = []
    upsert_sql_list = []
    group_size = 20
    total_samples = len(dataset["question"])
    author_id_counter = 1
    info_id_counter = 1
    info_type_to_id = {}
    author_name_to_id = {}
    for i in tqdm(range(0, total_samples, group_size)):
        question_group = dataset["question"][i:i+group_size]
        answer_group = dataset["answer"][i:i+group_size]

        qa_block = "\n\n".join([
            f"Q{j+1}: {q}\nA{j+1}: {a}"
            for j, (q, a) in enumerate(zip(question_group, answer_group))
        ])

        upsert_prompt = UPSERT_EXTRACTION_PROMPT.format(
            schema=schema_sql,
            qa_block=qa_block,
            info_type_list=info_type_to_id.keys()
        )
        upsert_sql = call_gpt_api(upsert_prompt)
        upsert_sql = parse_generated_sql(upsert_sql).replace("\\'", "''")
        sql_statements = [stmt.strip() for stmt in sqlparse.split(upsert_sql) if stmt.strip()]
        output_list.extend(sql_statements)

        author_id = -1

        for stmt in sql_statements:
            if "insert into author" in stmt.lower() and not "author_info" in stmt.lower():
                match = re.search(r"INSERT INTO author\s*\((.*?)\)\s*SELECT\s*(.+?)\s*WHERE", stmt, re.IGNORECASE | re.DOTALL)
                if match:
                    columns = [col.strip() for col in match.group(1).split(",")]
                    values = [val.strip() for val in match.group(2).split(",")]
                    if "full_name" in columns:
                        name_index = columns.index("full_name")
                        full_name = values[name_index].strip().strip("'").replace("''", "'")
                        if full_name not in author_name_to_id:
                            author_name_to_id[full_name] = author_id_counter
                            author_id_counter += 1
                        author_id = author_name_to_id[full_name]
            elif "insert into info" in stmt.lower():
                match = re.search(
                    r"INSERT INTO info\s*\(\s*info_id\s*,\s*info_type\s*\)\s*SELECT\s*\d+\s*,\s*'(.+?)'",
                    stmt,
                    re.IGNORECASE
                )
                if match:
                    info_type = match.group(1).replace("''", "'")
                    if info_type not in info_type_to_id:
                        info_type_to_id[info_type] = info_id_counter
                        info_id_counter += 1

        for stmt in sql_statements:            
            if "insert into author" in stmt.lower() and not "author_info" in stmt.lower():
                match = re.search(r"INSERT INTO author\s*\((.*?)\)\s*SELECT\s*(.+?)\s*WHERE", stmt, re.IGNORECASE | re.DOTALL)
                if match:
                    columns = [col.strip() for col in match.group(1).split(",")]
                    values = [val.strip() for val in match.group(2).split(",")]
                    name_index = columns.index("full_name")
                    full_name = values[name_index].strip().strip("'").replace("''", "'")
                    author_id = author_name_to_id[full_name]
                    values[0] = str(author_id)
                    safe_values = ", ".join(values)
                    stmt = f"""INSERT INTO author ({", ".join(columns)})
SELECT {safe_values}
WHERE NOT EXISTS (SELECT 1 FROM author WHERE full_name = '{full_name.replace("'", "''")}');"""
                    upsert_sql_list.append(stmt)

            elif "insert into info" in stmt.lower():
                match = re.search(
                    r"INSERT INTO info\s*\(\s*info_id\s*,\s*info_type\s*\)\s*SELECT\s*\d+\s*,\s*'(.+?)'",
                    stmt,
                    re.IGNORECASE
                )
                if match:
                    info_type = match.group(1).replace("''", "'")
                    info_id = info_type_to_id[info_type]
                    safe_info_type = info_type.replace("'", "''")
                    stmt = f"""INSERT INTO info (info_id, info_type)
SELECT {info_id}, '{safe_info_type}'
WHERE NOT EXISTS (SELECT 1 FROM info WHERE info_type = '{safe_info_type}');"""
                    upsert_sql_list.append(stmt)

            elif "insert into author_info" in stmt.lower():
                match = re.search(
                    r"INSERT INTO author_info\s*\(\s*author_id\s*,\s*info_id\s*,\s*note\s*\)\s*SELECT\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^']|'')*)'\s*WHERE",
                    stmt,
                    re.IGNORECASE | re.DOTALL
                )
                if match:
                    note = match.group(3).strip().replace("''", "'")
                    try:
                        info_type = next(itype for itype, iid in info_type_to_id.items() if iid == int(match.group(2)))
                    except StopIteration:
                        continue
                    real_author_id = author_id
                    real_info_id = info_type_to_id[info_type]
                    note = note.replace("\n", " ").replace("\r", " ").replace("\t", " ")
                    escaped_note = note.replace("'", "''")
                    stmt = f"""INSERT INTO author_info (author_id, info_id, note)
SELECT {real_author_id}, {real_info_id}, '{escaped_note}'
WHERE NOT EXISTS (
    SELECT 1 FROM author_info WHERE author_id = {real_author_id} AND info_id = {real_info_id}
);"""
                    upsert_sql_list.append(stmt)

            else:
                upsert_sql_list.append(stmt)

    os.makedirs("/home/jylee/SUN/data/SQL/", exist_ok=True)
    with open("/home/jylee/SUN/data/SQL/all_queries.sql", "w") as f:
        for sql in upsert_sql_list:
            f.write(sql + "\n\n\n")

    return schema_sql, upsert_sql_list

def create_duckdb_from_schema_and_upserts(db_path, schema_sql, upsert_sql_list):
    conn = duckdb.connect(database=db_path)

    try:
        for stmt in schema_sql.strip().split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt + ';')

        for upsert_sql in upsert_sql_list:
            try:
                conn.execute(upsert_sql)
            except Exception as e:
                print(f"Warning: Failed to execute SQL:\n{upsert_sql}\nError: {e}")
                continue

        print(f"Database successfully created at {db_path}")

    finally:
        conn.close()
  
if __name__ == "__main__":
    dataset = load_dataset("locuslab/TOFU", "full")['train']
    schema_sql, upsert_sql_list = get_schema_and_upserts(dataset)  
    create_duckdb_from_schema_and_upserts("/home/jylee/SUN/data/duckDB/tofu_data.db", schema_sql, upsert_sql_list)
        
# if __name__ == "__main__":
#     dataset = load_dataset("locuslab/TOFU", "full")['train']
#     schema_sql, upsert_sql_list = get_schema_and_upserts(dataset)

#     schema_sql = """DROP TABLE IF EXISTS author_info;
#     DROP TABLE IF EXISTS info;
#     DROP TABLE IF EXISTS author;

#     CREATE TABLE author (
#         author_id INTEGER PRIMARY KEY,
#         full_name TEXT NOT NULL,
#         birth_date DATE,
#         birth_place TEXT,
#         lgbtq BOOLEAN,
#         main_genre TEXT,
#         current_residence TEXT
#     );

#     CREATE TABLE info (
#         info_id INTEGER PRIMARY KEY,
#         info_type TEXT NOT NULL
#     );

#     CREATE TABLE author_info (
#         author_id INTEGER,
#         info_id INTEGER,
#         note TEXT, -- detailed description of the info instance
#         PRIMARY KEY (author_id, info_id),
#         FOREIGN KEY (author_id) REFERENCES author(author_id),
#         FOREIGN KEY (info_id) REFERENCES info(info_id)
#     );"""

#     with open("/home/jylee/SUN/data/SQL/all_queries.sql", "r") as f:
#         raw_query_blocks = f.read().strip().split("\n\n\n")

#     output_list = raw_query_blocks
#     upsert_sql_list = []

#     author_id_counter = 1
#     info_id_counter = 1
#     info_type_to_id = {}
#     author_name_to_id = {}

#     for upsert_sql in raw_query_blocks:
#         upsert_sql = parse_generated_sql(upsert_sql).replace("\\'", "''")
#         sql_statements = [stmt.strip() for stmt in sqlparse.split(upsert_sql) if stmt.strip()]

#         author_id = -1

#         for stmt in sql_statements:
#             if "insert into author" in stmt.lower() and not "author_info" in stmt.lower():
#                 match = re.search(r"INSERT INTO author\s*\((.*?)\)\s*SELECT\s*(.+?)\s*WHERE", stmt, re.IGNORECASE | re.DOTALL)
#                 if match:
#                     columns = [col.strip() for col in match.group(1).split(",")]
#                     values = [val.strip() for val in match.group(2).split(",")]
#                     if "full_name" in columns:
#                         name_index = columns.index("full_name")
#                         full_name = values[name_index].strip().strip("'").replace("''", "'")
#                         if full_name not in author_name_to_id:
#                             author_name_to_id[full_name] = author_id_counter
#                             author_id_counter += 1
#                         author_id = author_name_to_id[full_name]
#             elif "insert into info" in stmt.lower():
#                 match = re.search(
#                     r"INSERT INTO info\s*\(\s*info_id\s*,\s*info_type\s*\)\s*SELECT\s*\d+\s*,\s*'(.+?)'",
#                     stmt,
#                     re.IGNORECASE
#                 )
#                 if match:
#                     info_type = match.group(1).replace("''", "'")
#                     if info_type not in info_type_to_id:
#                         info_type_to_id[info_type] = info_id_counter
#                         info_id_counter += 1

#         for stmt in sql_statements:            
#             if "insert into author" in stmt.lower() and not "author_info" in stmt.lower():
#                 match = re.search(r"INSERT INTO author\s*\((.*?)\)\s*SELECT\s*(.+?)\s*WHERE", stmt, re.IGNORECASE | re.DOTALL)
#                 if match:
#                     columns = [col.strip() for col in match.group(1).split(",")]
#                     values = [val.strip() for val in match.group(2).split(",")]
#                     name_index = columns.index("full_name")
#                     full_name = values[name_index].strip().strip("'").replace("''", "'")
#                     author_id = author_name_to_id[full_name]
#                     values[0] = str(author_id)
#                     safe_values = ", ".join(values)
#                     stmt = f"""INSERT INTO author ({", ".join(columns)})
# SELECT {safe_values}
# WHERE NOT EXISTS (SELECT 1 FROM author WHERE full_name = '{full_name.replace("'", "''")}');"""
#                     upsert_sql_list.append(stmt)

#             elif "insert into info" in stmt.lower():
#                 match = re.search(
#                     r"INSERT INTO info\s*\(\s*info_id\s*,\s*info_type\s*\)\s*SELECT\s*\d+\s*,\s*'(.+?)'",
#                     stmt,
#                     re.IGNORECASE
#                 )
#                 if match:
#                     info_type = match.group(1).replace("''", "'")
#                     info_id = info_type_to_id[info_type]
#                     safe_info_type = info_type.replace("'", "''")
#                     stmt = f"""INSERT INTO info (info_id, info_type)
# SELECT {info_id}, '{safe_info_type}'
# WHERE NOT EXISTS (SELECT 1 FROM info WHERE info_type = '{safe_info_type}');"""
#                     upsert_sql_list.append(stmt)

#             elif "insert into author_info" in stmt.lower():
#                 match = re.search(
#                     r"INSERT INTO author_info\s*\(\s*author_id\s*,\s*info_id\s*,\s*note\s*\)\s*SELECT\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^']|'')*)'\s*WHERE",
#                     stmt,
#                     re.IGNORECASE | re.DOTALL
#                 )
#                 if match:
#                     note = match.group(3).strip().replace("''", "'")
#                     try:
#                         info_type = next(itype for itype, iid in info_type_to_id.items() if iid == int(match.group(2)))
#                     except StopIteration:
#                         continue
#                     real_author_id = author_id
#                     real_info_id = info_type_to_id[info_type]
#                     note = note.replace("\n", " ").replace("\r", " ").replace("\t", " ")
#                     escaped_note = note.replace("'", "''")
#                     stmt = f"""INSERT INTO author_info (author_id, info_id, note)
# SELECT {real_author_id}, {real_info_id}, '{escaped_note}'
# WHERE NOT EXISTS (
#     SELECT 1 FROM author_info WHERE author_id = {real_author_id} AND info_id = {real_info_id}
# );"""
#                     upsert_sql_list.append(stmt)

#             else:
#                 upsert_sql_list.append(stmt)
    
#     create_duckdb_from_schema_and_upserts("/home/jylee/SUN/data/duckDB/tofu_data.db", schema_sql, upsert_sql_list)

    # schema_sql = """CREATE TABLE author (
    #     author_id INTEGER PRIMARY KEY,
    #     full_name TEXT NOT NULL,
    #     birth_date DATE,
    #     birth_place TEXT,
    #     lgbtq BOOLEAN,
    #     main_genre TEXT,
    #     current_residence TEXT
    # );

    # CREATE TABLE info (
    #     info_id INTEGER PRIMARY KEY,
    #     info_type TEXT NOT NULL
    # );

    # CREATE TABLE author_info (
    #     author_id INTEGER,
    #     info_id INTEGER,
    #     note TEXT, -- detailed description of the info instance
    #     PRIMARY KEY (author_id, info_id),
    #     FOREIGN KEY (author_id) REFERENCES author(author_id),
    #     FOREIGN KEY (info_id) REFERENCES info(info_id)
    # );"""
