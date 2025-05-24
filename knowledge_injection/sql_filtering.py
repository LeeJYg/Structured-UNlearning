

import os
import re
import sqlparse
from tqdm import tqdm

def main():
    input_path = "/home/jylee/SUN/data/SQL/01_all_queries.sql"
    output_path = "/home/jylee/SUN/data/SQL/all_queries.sql"

    author_id_counter = 1
    info_id_counter = 1
    info_type_to_id = {}
    author_name_to_id = {}

    with open(input_path, "r") as f:
        raw_sql = f.read().strip()

    sql_statements = [stmt.strip() for stmt in raw_sql.split(";\n\n") if stmt.strip()]
    upsert_sql_list = []
    author_id = -1

    # First pass to assign IDs
    for stmt in sql_statements:
        if "insert into author" in stmt.lower() and "author_info" not in stmt.lower():
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

    # Second pass to rewrite statements
    for stmt in sql_statements:
        if "insert into author" in stmt.lower() and "author_info" not in stmt.lower():
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

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        for sql in upsert_sql_list:
            f.write(sql + "\n\n\n")

if __name__ == "__main__":
    main()