import duckdb
import os

def duckDBCreate(csv_file_path, duckdb_file_path):
    conn = duckdb.connect(duckdb_file_path)
    
    csv_files = [f for f in os.listdir(csv_file_path) if f.endswith(".csv")]

    error_files = []

    for csv_file in csv_files:
        table_name = os.path.splitext(csv_file)[0] 
        csv_path = os.path.join(csv_file_path, csv_file)

        if csv_file == 'movie_info.csv':
            query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto('{csv_path}', strict_mode=false, ignore_errors=true);"
        elif csv_file == 'name.csv':
            query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto('{csv_path}', strict_mode=false);"
        else:
            query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto('{csv_path}');"

        print(f"📂 Converting {csv_file} → Table: {table_name}")
        
        try:
            conn.execute(query)
            print(f"✅ {table_name} created successfully!")
        except Exception as e:
            print(f"❌ Error processing {csv_file}: {e}")
            error_files.append(csv_file)

    conn.close()

    if error_files:
        print("\n⚠️ The following files encountered errors during processing:")
        for err_file in error_files:
            print(f"   - {err_file}")
    else:
        print("\n✅ All CSV files loaded successfully!")
        
        
if __name__ == "__main__":
    
    db_path = "/home/jylee/SUN/imdb.duckdb"
    csv_dir = "/home/jylee/SUN/imdb"
    
    duckDBCreate(csv_dir, db_path)