import yaml
import copy
import duckdb
import os
import json
import numpy as np
from scipy.stats import sem, hmean, ks_2samp
from natsort import natsorted

from openai import OpenAI
from utils.api_key import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def call_gpt_api(prompt):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at converting structured data into natural language descriptions."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()

def has_actual_results(result_list):
    def is_actual_value(val):
        if isinstance(val, (list, tuple)):
            return any(is_actual_value(item) for item in val)
        return val not in (None, 0, "", [])
    
    return is_actual_value(result_list)

def get_model_identifiers_from_yaml(model_family):
    model_configs  = {}
    with open("/home/jylee/SUN/config/model_config.yaml", "r") as f:
        model_configs = yaml.load(f, Loader=yaml.FullLoader)
    return model_configs[model_family]

def merge_dicts(a, b):
    a_copy = copy.deepcopy(a)

    for key, value in b.items():
        if key in a_copy:
            if isinstance(a_copy[key], dict) and isinstance(value, dict):
                a_copy[key] = merge_dicts(a_copy[key], value)
            elif isinstance(a_copy[key], list) and isinstance(value, list):
                a_copy[key] = a_copy[key]
            else:
                a_copy[key] = value
        else:
            a_copy[key] = value

    a_copy = {k: a_copy[k] for k in natsorted(a_copy)}    
    return a_copy

def get_total_len(name, forget_rate):
    if name == 'eval_real_author_wo_options.json':
        return 100
    elif name == 'eval_real_world_wo_options.json':
        return 117
    elif name == 'eval_log.json':
        return 300
    else:
        if forget_rate == 'forget01':
            return 40
        elif forget_rate == 'forget05':
            return 200
        else:
            return 300

def interleave(a, b, size):
    assert len(a) == len(b)
    assert size > 0
    c = []
    for i in range(0, len(a), size):
        c.extend(a[i:i+size])
        c.extend(b[i:i+size])
    return c

def interleave_eval_result_dict(eval_result_dict, forget_rate, large_bsz, num_processes=2):
    small_bsz = large_bsz//4
    for k, v in eval_result_dict.items():
        for metric, value in v.items():
            bsz = small_bsz if 'perturb' in metric or 'paraphrase' in metric else large_bsz
            total_len = get_total_len(k, forget_rate)
            a = value[0:len(value)//2]
            b = value[len(value)//2:]
            eval_result_dict[k][metric] = interleave(a, b, bsz)[:total_len]
    return eval_result_dict

def duckDBCreate(csv_dir_path, duckdb_file_path):
    conn = duckdb.connect(duckdb_file_path)
    
    csv_files = [f for f in os.listdir(csv_dir_path) if f.endswith(".csv")]

    error_files = []

    for csv_file in csv_files:
        table_name = os.path.splitext(csv_file)[0] 
        csv_path = os.path.join(csv_dir_path, csv_file)

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
    
