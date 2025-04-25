import duckdb
import json

from tupleExtraction import tupleExtractor
from utils import duckDBCreate

retained_table = ['kind_type', 'link_type', 'char_name', 'role_type', 'info_type', 'comp_cast_type', 'company_name', 'company_type', 'keyword', 'name', 'person_info', 'aka_name']

def create_imdb_tables(duckdb_filename, schema_file_path):
    con = duckdb.connect(duckdb_filename)
    
    tables = con.execute("SHOW TABLES").fetchall()
    
    for table in tables:
        table_name = table[0]
        if table_name not in retained_table:
            con.execute(f"DROP TABLE IF EXISTS {table_name};")
            print(f"[INFO] Table '{table_name}' dropped.")
    
    with open(schema_file_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        
    for schema in schema_sql.split('\n\n'):
        table_name = schema.split('TABLE')[1].split('(')[0].strip()
        if table_name not in retained_table:
            con.execute(schema)

    con.close()
    
def index_builder(duckdb_filename, index_file_path):
    con = duckdb.connect(duckdb_filename)
    
    with open(index_file_path, "r", encoding="utf-8") as f:
        index_sql = f.read()
    
    for index_command in index_sql.split('\n'):
        con.execute(index_command)
        print(f"[INFO] Index '{index_command}' created.")
    
    con.close()

def insert_data_into_tables(duckdb_filename, data_dict):
    con = duckdb.connect(duckdb_filename)
    
    if not isinstance(data_dict['title'], list):
        data_dict['title'] = [data_dict['title']]

    for table_name, value in data_dict.items():
        if not value:
            continue
        
        if isinstance(value, list):

            columns_info = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            if not columns_info:
                print(f"[WARN] 테이블 '{table_name}'이(가) DuckDB에 존재하지 않습니다. 건너뜀.")
                continue
            
            row_list = []
            
            for row in value:
                row_list.append(tuple(row.values()))
                
            num_cols = len(columns_info)  #
            placeholders = ", ".join(["?"] * num_cols)
            insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

            # executemany로 튜플 리스트를 한 번에 삽입
            con.executemany(insert_sql, row_list)
        print(f"[INFO] 테이블 '{table_name}'에 {len(row_list)}개 행 삽입 완료.")

    print("[INFO] Data Insertion Completed.")

    con.close()


def deletedDuckDBCraetion(tuple_num, duckdb_filename, tuple_file_path=None):
    csv_dir = "/home/jylee/SUN/imdb"
    
    duckDBCreate(csv_dir, duckdb_filename)
    
    schema_file_path = "/home/jylee/SUN/imdb/imdb_schema.sql"
    index_file_path = "/home/jylee/SUN/imdb/imdb_index.sql"

    create_imdb_tables(duckdb_filename, schema_file_path)

    if tuple_file_path == None:
        tuples = tupleExtractor(tuple_num, mode='deletion')
    else:
        with open(tuple_file_path, "r", encoding="utf-8") as f:
            tuples = json.load(f)
    
    if tuple_num == -1:
        tuple_num = len(tuples)
    tuples = tuples[:tuple_num]
    
    for data_dict in tuples:
        insert_data_into_tables(duckdb_filename, data_dict)

    index_builder(duckdb_filename, index_file_path)

    print("[INFO] DuckDB Created and Data Inserted Successfully.")

    
if __name__ == "__main__":
    deleted_duckdb_path = "/home/jylee/SUN/imdb/duckdb/deleted_imdb.duckdb"
    
    deletedDuckDBCraetion(tuple_num=5, duckdb_filename=deleted_duckdb_path)