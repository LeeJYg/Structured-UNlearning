import psycopg2
import json
import os
import argparse

from transformers import AutoTokenizer

first_joinable_tables = {
    "kind_type": "id",
    "cast_info": "movie_id",
    "movie_info": "movie_id",
    "movie_info_idx": "movie_id",
    "movie_keyword": "movie_id",
    "movie_companies": "movie_id",
    "aka_title": "movie_id",
    "movie_link": "movie_id",
    "complete_cast": "movie_id",
}

second_joinable_tables = {
    "cast_info": {
        "char_name": "person_role_id",
        "role_type": "role_id",
        "name": "person_id",
    },
    "name": {
        "aka_name": "id",
    },
    "name": {
        "person_info": "id",
    },
    "person_info": {
        "info_type": "info_type_id",
    },
    "movie_info": {
        "info_type": "info_type_id",
    },
    "movie_info_idx": {
        "info_type": "info_type_id",
    },
    "complete_cast": {
        "comp_cast_type": ["subject_id", "status_id"],
    },
    "movie_link": {
        "link_type": "link_type_id",
    },
    "movie_keyword": {
        "keyword": "keyword_id",
    },
    "movie_companies": {
        "company_name": "company_id",
        "company_type": "company_type_id",
    },
}

foreign_keys = {
    "char_name": "id",  # char_name.id = cast_info.person_role_id
    "role_type": "id",  # role_type.id = cast_info.role_id
    "name": "id",       # name.id = cast_info.id
    "aka_name": "person_id",   # aka_name.person_id = name.id
    "person_info": "person_id",  # person_info.person_id = name.id
    "info_type": "id",  # info_type.id = movie_info.info_type_id
    "comp_cast_type": "id",  # comp_cast_type.id = complete_cast.subject_id OR status_id
    "link_type": "id",  # link_type.id = movie_link.link_type_id
    "keyword": "id",  # keyword.id = movie_keyword.keyword_id
    "company_name": "id",  # company_name.id = movie_companies.company_id
    "company_type": "id",  # company_type.id = movie_companies.company_type_id
}

def fetch_recursive_data(cursor, table, table_rows, table_columns, second_joinable_tables, foreign_keys, visited_tables):
    if table not in second_joinable_tables:
        return {}

    related_data = {}
 
    join_values = {related_table: set() for related_table in second_joinable_tables[table]}

    for row in table_rows:
        row_dict = dict(zip(table_columns, row))
        
        for related_table, join_column in second_joinable_tables[table].items():
            if related_table not in foreign_keys:
                print(f"Warning: {related_table}에 대한 외래 키 정보가 없음. 스킵됨.")
                continue
            
            related_table_column = foreign_keys[related_table]

            if isinstance(join_column, list):
                for col in join_column:
                    if col in row_dict and row_dict[col] is not None:
                        join_values[related_table].add(row_dict[col])
            else:
                if join_column in row_dict and row_dict[join_column] is not None:
                    join_values[related_table].add(row_dict[join_column])

    for related_table, values in join_values.items():
        if not values:
            continue
        
        related_table_column = foreign_keys[related_table]
        
        placeholders = ', '.join(['%s'] * len(values))
        query = f"SELECT * FROM {related_table} WHERE {related_table_column} IN ({placeholders})"
        
        cursor.execute(query, list(values))
        related_rows = cursor.fetchall()
        related_columns = [desc[0] for desc in cursor.description]

        if related_rows:
            if related_table not in related_data:
                related_data[related_table] = []
            
            related_data[related_table].extend([dict(zip(related_columns, r)) for r in related_rows])
            
            if related_table not in visited_tables:
                visited_tables.add(related_table)
                deeper_data = fetch_recursive_data(cursor, related_table, related_rows, related_columns, second_joinable_tables, foreign_keys, visited_tables)

                for key, value in deeper_data.items():
                    if key in related_data:
                        related_data[key].extend(value)
                    else:
                        related_data[key] = value
    
    return related_data

def joinable_tuple_finder(title_tuple_num):
    conn = psycopg2.connect(
        dbname="postgres",
        user="jylee",
        host="localhost",
        port="5432"
    )
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT *
        FROM title t
        WHERE t.kind_id = 1
            AND t.production_year IS NOT NULL
            AND EXISTS (SELECT 1 FROM cast_info WHERE movie_id = t.id)
            AND EXISTS (SELECT 1 FROM movie_info WHERE movie_id = t.id)
            AND EXISTS (SELECT 1 FROM movie_keyword WHERE movie_id = t.id)
            AND EXISTS (SELECT 1 FROM movie_companies WHERE movie_id = t.id)
        ORDER BY t.production_year DESC
        LIMIT {title_tuple_num};
    """)
    
    title_rows = cursor.fetchall()
    title_columns = [desc[0] for desc in cursor.description]
    
    output_dir = "unlearning_target"
    os.makedirs(output_dir, exist_ok=True)
    
    results = []
    
    for title_row in title_rows:
        title_id = title_row[0]
        title_kind_id = title_row[3]
        title_data = dict(zip(title_columns, title_row))
        related_data = {"title": title_data}
        
        visited_tables = set()
        
        for table, column in first_joinable_tables.items():
            if table == "kind_type":
                cursor.execute(f"SELECT * FROM {table} WHERE {column} = %s", (title_kind_id,))
                table_rows = cursor.fetchall()            
                table_columns = [desc[0] for desc in cursor.description]
            else:
                cursor.execute(f"SELECT * FROM {table} WHERE {column} = %s", (title_id,))
                table_rows = cursor.fetchall()            
                table_columns = [desc[0] for desc in cursor.description]

            if table == "movie_link":
                movie_link_entries = []
                if table_rows != []:
                    for row in table_rows:
                        movie_link_data = dict(zip(table_columns, row))
                        linked_movie_id = movie_link_data['linked_movie_id']
                        
                        cursor.execute("SELECT * FROM title WHERE id = %s", (linked_movie_id,))
                        linked_movie_row = cursor.fetchall()
                        linked_movie_columns = [desc[0] for desc in cursor.description]
                        if linked_movie_row:
                            linked_movie_data = dict(zip(linked_movie_columns, linked_movie_row[0]))
                            movie_link_data["linked_movie"] = linked_movie_data
                            
                        movie_link_entries.append(movie_link_data)
                
                    related_data[table] = movie_link_data
                else:
                    related_data[table] = []
            else:
                related_data[table] = [dict(zip(table_columns, row)) for row in table_rows]
            
            if table in second_joinable_tables:
                deeper_data = fetch_recursive_data(cursor, table, table_rows, table_columns, second_joinable_tables, foreign_keys, visited_tables)
                for key, value in deeper_data.items():
                    if key in related_data:
                        if isinstance(related_data[key], list):
                            related_data[key].extend(value)
                        else:
                            related_data[key] = [related_data[key]] + value
                    else:
                        related_data[key] = value
        
        results.append(related_data)
        
    return results

def tupleExtractor(tuple_num, mode=None):
    joinable_tuples = joinable_tuple_finder(tuple_num)
        
    if mode == 'deletion':
        one_hop_table_list = [k for k in first_joinable_tables if k != 'kind_type']
        one_hop_table_list.append('title')

        for tuple in joinable_tuples:
            table_list = list(tuple.keys())
            for table in table_list:
                if table not in one_hop_table_list:
                    del tuple[table]

    return joinable_tuples

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate unlearning target documents from title table.")
    parser.add_argument("--title_tuple", type=int, default=20, help="Number of title tuples to process")
    args = parser.parse_args()
        
    joinable_tuples = joinable_tuple_finder(args.title_tuple)

    output_dir = "/home/jylee/SUN/unlearning_target/tuples"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"joinable_tuples_${args.title_tuple}.json")
    
    with open(file_path, "a", encoding="utf-8") as f:
        json.dump(joinable_tuples, f, indent=4, ensure_ascii=False)

    print(f"Joinable tuples saved to {file_path}")