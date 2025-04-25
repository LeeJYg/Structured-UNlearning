from openai import OpenAI
from tqdm import tqdm
import tiktoken
import json
import os
import traceback

from transformers import AutoTokenizer
from collections import defaultdict
from tupleExtraction import tupleExtractor
from prompts.templates import FIRST_SUB_DATA_PROMPT, FOLLOWUP_SUB_DATA_PROMPT

from utils import call_gpt_api

GENERATED_TEXT_LENGTH = 250000

SUB_DATABASES = {
    "basic_info": ["title", "kind_type"],
    "movie_info": ["movie_info", "movie_info_idx", "info_type"],
    "cast_info": ["cast_info", "role_type", "char_name", "aka_name", "name", "person_info", "info_type"],
    "keyword_info": ["movie_keyword", "keyword"],
    "company_info": ["movie_companies", "company_name", "company_type"],
    "alternate_titles": ["aka_title"],
    "movie_links": ["movie_link", "link_type"],
    "complete_cast": ["complete_cast", "comp_cast_type"]
}

kind_type_map = {
    1: 'movie',
    2: 'tv series',
    3: 'tv movie',
    4: 'video movie',
    5: 'tv mini series',
    6: 'video game',
    7: 'episode',
}
COMP_CAST_TYPE_MAP = {
    1: "cast",
    2: "crew",
    3: "complete",
    4: "complete+verified"
}

id_keys = ['id', 'kind_id', 'movie_id', 'person_id', 'role_id', 'person_role_id', 'info_type_id', 'keyword_id', 'company_id', 'company_type_id', 'link_type_id', 'subject_id', 'status_id']

tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")

def remove_null_values(data):
    if isinstance(data, list):
        return [remove_null_values(v) for v in data if v is not None]
    elif isinstance(data, dict):
        return {k: remove_null_values(v) for k, v in data.items() if v is not None}
    else:
        return data
    
def remove_id_keys(data, id_keys):
    if isinstance(data, list):
        return [remove_id_keys(v, id_keys) for v in data if v is not None]
    elif isinstance(data, dict):
        return {k: remove_id_keys(v, id_keys) for k, v in data.items() if k not in id_keys}
    else:
        return data

def filtering_sub_data(sub_data, info_type_map):
    if 'kind_type' in sub_data:
        kind = kind_type_map.get(sub_data['title'][0]['kind_id'])
        sub_data['title'][0]['kind'] = kind
        del sub_data['kind_type']
        del sub_data['title'][0]['kind_id']

    if 'info_type' in sub_data:
        del sub_data['info_type']
        
        for table in ['movie_info', 'movie_info_idx']:
            filtered_entries = []
            if table in sub_data:
                for entry in sub_data[table]:
                    if 'info_type_id' in entry:
                        info_type_id = entry['info_type_id']                
                        filtered_entry = {k: v for k, v in entry.items() if k not in ['id', 'movie_id', 'info_type_id']}
                        filtered_entry['info_type'] = info_type_map.get(info_type_id, "Unknown Info Type")
                        filtered_entries.append(filtered_entry)
            
            del sub_data[table]
            sub_data[table] = filtered_entries
    
    if 'movie_keyword' in sub_data:
        #keyword_map = {entry['id']: {'keyword': entry['keyword'], 'phonetic_code': entry['phonetic_code']} for entry in sub_data['keyword']}
        keyword_map = {entry['id']: {'keyword': entry['keyword']} for entry in sub_data['keyword']}
        extracted_keywords = []

        for entry in sub_data['movie_keyword']:
            keyword_id = entry['keyword_id']
            if keyword_id in keyword_map:
                extracted_keywords.append(keyword_map[keyword_id])

        del sub_data['movie_keyword']
        sub_data['keyword'] = extracted_keywords
    
    if 'movie_companies' in sub_data:
        company_map = {entry['id']: {'name': entry['name'], 'country_code': entry['country_code'], 'name_pcode_nf': entry['name_pcode_nf'], 'name_pcode_sf': entry['name_pcode_sf'], 'md5sum': entry['md5sum']} for entry in sub_data['company_name']}
        company_type_map = {entry['id']: entry['kind'] for entry in sub_data['company_type']}
        
        extracted_companies = []
        for entry in sub_data['movie_companies']:
            company_id = entry['company_id']
            company_type_id = entry['company_type_id']
            
            company_data = {}
            
            if company_id in company_map:
            #    company_data.update({
            #         'name': company_map[company_id]['name'],
            #         'country': company_map[company_id]['country_code'],
            #         'name_pcode_nf': company_map[company_id]['name_pcode_nf'],
            #         'name_pcode_sf': company_map[company_id]['name_pcode_sf'],
            #         'md5sum': company_map[company_id]['md5sum']
            #     })
                company_data.update({
                    'name': company_map[company_id]['name'],
                })
            if company_type_id in company_type_map:
                company_data['type'] = company_type_map[company_type_id]
            
            extracted_companies.append(company_data)
                
        del sub_data['movie_companies']
        del sub_data['company_name']
        del sub_data['company_type']
        sub_data['movie_companies'] = extracted_companies
    
    if 'movie_link' in sub_data and 'link_type' in sub_data:
        link_type_map = {entry['id']: entry['link'] for entry in sub_data['link_type']}

        extracted_links = []
        for entry in sub_data['movie_link']:
            link_data = {}

            if 'link_type_id' in entry and entry['link_type_id'] in link_type_map:
                link_data['link_type'] = link_type_map[entry['link_type_id']]
            
            if 'linked_movie' in entry and isinstance(entry['linked_movie'], dict):
                linked_movie_data = entry['linked_movie']
                linked_movie_data = remove_null_values(linked_movie_data)
                
                kind = kind_type_map.get(linked_movie_data.get('kind_id'))
                
                del linked_movie_data['kind_id']
                linked_movie_data['kind'] = kind
                
                link_data['linked_movie'] = linked_movie_data

            extracted_links.append(link_data)

        del sub_data['movie_link']
        del sub_data['link_type']
        sub_data['movie_links'] = extracted_links

    if 'complete_cast' in sub_data:
        extracted_cast = []
        
        for entry in sub_data['complete_cast']:
            cast_data = {}
            
            if 'subject_id' in entry and entry['subject_id'] in COMP_CAST_TYPE_MAP:
                cast_data['subject'] = COMP_CAST_TYPE_MAP[entry['subject_id']]
            if 'status_id' in entry and entry['status_id'] in COMP_CAST_TYPE_MAP:
                cast_data['status'] = COMP_CAST_TYPE_MAP[entry['status_id']]
            
            extracted_cast.append(cast_data)
        
        del sub_data['complete_cast']
        sub_data['complete_cast'] = extracted_cast
    
    if 'comp_cast_type' in sub_data:
        del sub_data['comp_cast_type']

    return sub_data

def split_sub_data(sub_data, max_token):
    chunks = []
    current_chunk = {}
    current_tokens = 0
    
    for key, value in sub_data.items():
        if isinstance(value, list):
            temp_list = []
            temp_tokens = 0
            
            for item in value:
                item_text = json.dumps(item, indent=4)
                item_tokens = tokenizer.encode(item_text)
                
                if temp_tokens + len(item_tokens) > max_token:
                    current_chunk[key] = temp_list
                    chunks.append(json.dumps(current_chunk, ensure_ascii=False))
                    current_chunk = {}
                    temp_list = []
                    temp_tokens = 0
                
                temp_list.append(item)
                temp_tokens += len(item_tokens)
            
            if temp_list:
                current_chunk[key] = temp_list
                temp_list = []
        else:
            key_value_pair = {key: value}
            kv_json = json.dumps(key_value_pair, ensure_ascii=False)
            kv_tokens = tokenizer.encode(kv_json) 
            
            if current_tokens + len(kv_tokens) > max_token:
                chunks.append(json.dumps(current_chunk, ensure_ascii=False))
                current_chunk = {}
                current_tokens = 0

            current_chunk[key] = value
            current_tokens += len(kv_tokens)

    if current_chunk:
        chunks.append(json.dumps(current_chunk, ensure_ascii=False))
        
    return chunks

def generate_iterative_text(sub_db, sub_data, entity_info, max_token=2048):
    generated_docu = []
    data_chunks = split_sub_data(sub_data, max_token=max_token)
    
    initial_prompt = FIRST_SUB_DATA_PROMPT.format(
        category=sub_db,
        title=entity_info['title'],
        kind=entity_info['kind'],
        data=json.dumps(data_chunks[0], indent=4)
    )
    generated_text = call_gpt_api(initial_prompt)
    generated_docu.append(generated_text)
    
    for chunk in data_chunks[1:]:
        followup_prompt = FOLLOWUP_SUB_DATA_PROMPT.format(
            previous_summary=generated_text,
            new_data=json.dumps(chunk, indent=4),
            title=entity_info['title'],
            kind=entity_info['kind']
        )
        generated_text = call_gpt_api(followup_prompt)
        generated_docu.append(generated_text)
    
    if len(generated_docu) > 1:
        generated_docu = "\n\n".join(generated_docu)
    else:
        generated_docu = generated_docu[0]
    
    return generated_docu


def generate_text_from_cast_tuple(cast_entries, movie_entry, info_type_map):
    movie_id = cast_entries[0]["movie_id"]
    person_id = cast_entries[0]["person_id"]

    title_info = "No information available."
    name_info = "No information available."
    aka_name_info = "No information available."
    
    if movie_id is not None:
        for title_entry in movie_entry.get("title", []):
            if title_entry['id'] == movie_id:
                title_info = title_entry['title']
                title_kind = kind_type_map.get(title_entry['kind_id'])
                break
         
    if person_id is not None:
        for name_entry in movie_entry.get("name", []):
            if name_entry['id'] == person_id:
                name_info = {k: name_entry[k] for k in ["id", "name", "gender"]}
                name_id = name_entry['id']
                
                # if name_id is not None:
                #     for aka_name_entry in movie_entry.get("aka_name", []):
                #         if aka_name_entry['id'] == name_id:
                #             aka_name_info = aka_name_entry
                #             break
                break   
    
    person_total_info = {
        'title': {'title': title_info, 'kind': title_kind},
        "person": name_info,
        #"credited name": aka_name_info,
        "role": [],
        "character in movie": [],
        "cast info": [],
    }
    
    for cast_entry in cast_entries:
        role_id = cast_entry["role_id"]
        person_role_id = cast_entry['person_role_id']
                
        role_info = "No information available."
        if role_id is not None:
            for role_entry in movie_entry.get("role_type", []):
                if role_entry["id"] == role_id:
                    role_info = role_entry['role']
                    break

        char_name_info = "No information available."
        if person_role_id is not None:
            for char_name_entry in movie_entry.get("char_name", []):
                if char_name_entry["id"] == person_role_id:
                    char_name_info = {k: char_name_entry[k] for k in ["id", "name"]}
                    break

            
        # if person_info_person_id is not None:
        #     for person_info_entry in movie_entry.get("person_info", []):
        #         if person_info_entry['person_id'] == person_info_person_id:
        #             info_type_id = person_info_entry['info_type_id']                
        #             filtered_person_info = {k: v for k, v in person_info_entry.items() if k not in ['id', 'person_id', 'info_type_id']}
        #             filtered_person_info['info_type'] = info_type_map.get(info_type_id, "Unknown Info Type")
        #             person_info_info.append(filtered_person_info)

            
        sub_data = {
            "role": role_info,
            "character in movie": char_name_info,
            "cast info": cast_entry,
            # "person_info": person_info_info,
        }

        sub_data = remove_id_keys(remove_null_values(sub_data), id_keys)
        sub_data = {k: v for k, v in sub_data.items() if v != 'No information available.'}
        
        if 'role' in sub_data.keys():
            person_total_info['role'].append(sub_data['role'])
        if 'character in movie' in sub_data.keys():
            person_total_info['character in movie'].append(sub_data['character in movie'])
        if 'cast info' in sub_data.keys():
            person_total_info['cast info'].append(sub_data['cast info'])

    person_total_info = remove_id_keys(remove_null_values(person_total_info), id_keys)
    person_total_info = {k: v for k, v in person_total_info.items() if v != 'No information available.' and v != []}

    text = generate_iterative_text("cast_info", person_total_info, entity_info={'title': title_info, 'kind': title_kind})

    return person_total_info, text

def process_data_and_generate_text(movie_entry):
    title_data = movie_entry["title"]
    media_type = movie_entry["kind_type"]

    movie_entry['title'] = [title_data]
    
    info_type_map = {entry['id']: entry['info'] for entry in movie_entry.get("info_type", [])}
    
    sub_texts = {}
    
    base_data = []

    for sub_db, tables in SUB_DATABASES.items():
        if sub_db == "cast_info":
            cast_info = movie_entry.get('cast_info', [])
            cast_sentences = []
            person_id_to_cast_entries = defaultdict(list)
            
            for entry in cast_info:
                person_id_to_cast_entries[entry['person_id']].append(entry)
            
            person_info = []
            for person_id, cast_entries in person_id_to_cast_entries.items():
                person_total_info, sentence = generate_text_from_cast_tuple(cast_entries, movie_entry, info_type_map)
                cast_sentences.append(sentence)
                person_info.append(person_total_info)
                
            base_data.append(person_info)
                
            sub_texts["cast_info"] = " ".join(cast_sentences)
        else:
            sub_data = {table: remove_null_values(movie_entry.get(table, [])) for table in tables}
        
            sub_data = filtering_sub_data(sub_data, info_type_map)
            
            if all(isinstance(value, list) and not value for value in sub_data.values()):
                sub_texts[sub_db] = "No relevant information available."
                continue 
            
            sub_data = {k: v for k, v in sub_data.items() if v}  
            base_data.append(sub_data)
            
            sub_texts[sub_db] = generate_iterative_text(sub_db, sub_data, entity_info={'title': title_data['title'], 'kind': kind_type_map.get(movie_entry.get("title", [])[0]['kind_id'])})

    return base_data, sub_texts

def textConstruct(tuple_num, text_output_dir, tuple_output_dir):
    tokenizer = AutoTokenizer.from_pretrained("NousResearch/Llama-2-7b-chat-hf")
    tokenizer.pad_token = tokenizer.eos_token
    
    imdb_data = tupleExtractor(tuple_num=tuple_num, mode=None)
    
    # 추가된 부분
    used_tuple_num = 300
    imdb_data = imdb_data[used_tuple_num:]
    
    total_token = 0
    used_tuple_num = 0
    
    results = []
    base_data_results = []
    for entry in tqdm(imdb_data):
        try:
            base_data, dict_text = process_data_and_generate_text(entry)
            base_data_results.append(base_data)
            document = ""
            
            for sub_database, sentence in dict_text.items():
                if sentence == "No relevant information available.":
                    continue

                if isinstance(sentence, list) and len(sentence) > 0:
                    document += '\n'.join(sentence)
                    continue
                            
                document += sentence + "\n\n"

            results.append({
                "title": entry["title"][0]["title"],
                "dict_description": document,
            })
            
            new_token = len(tokenizer.encode(document))
            total_token += new_token
            
            used_tuple_num += 1
            if total_token > GENERATED_TEXT_LENGTH:
                break
        except:
            print(f"Error processing entry: {entry}")
            traceback.print_exc()
            continue

    if not os.path.exists(text_output_dir):
        os.makedirs(text_output_dir, exist_ok=True)
    text_output_path = os.path.join(text_output_dir, f"text_descriptions_adaptive_{used_tuple_num}.json")
    with open(text_output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    
    if not os.path.exists(tuple_output_dir):
        os.makedirs(tuple_output_dir, exist_ok=True)
    tuple_output_path = os.path.join(tuple_output_dir, f"tuple_descriptions_adaptive_{used_tuple_num}.json")
    with open(tuple_output_path, "w", encoding="utf-8") as f:
        json.dump(imdb_data[:used_tuple_num], f, indent=4, ensure_ascii=False)
        
    base_data_output_dir = '/home/jylee/SUN/unlearning_target/base_data'
    if not os.path.exists(base_data_output_dir):
        os.makedirs(base_data_output_dir, exist_ok=True)
    with open(os.path.join(base_data_output_dir, f"base_data_{used_tuple_num}.json"), "w", encoding="utf-8") as f:
        json.dump(base_data_results, f, indent=4, ensure_ascii=False)
    
    texts = [example["dict_description"] for example in results]

    total_token = len(tokenizer.encode("".join(texts)))
    print(f"Total Training Token: {total_token}")


if __name__ == "__main__":
    text_output_dir = '/home/jylee/SUN/unlearning_target/text'
    tuple_output_dir = '/home/jylee/SUN/unlearning_target/tuples'
    
    textConstruct(tuple_num=1000, text_output_dir=text_output_dir, tuple_output_dir=tuple_output_dir)