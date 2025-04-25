import psycopg2
import re
import os
import argparse

from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(
    "locuslab/tofu_ft_llama2-7b",
)
    
# attribute 접근이 가능한 객체로 변환하는 클래스 (이전과 동일)
class Obj:
    def __init__(self, d):
        for k, v in d.items():
            if isinstance(v, dict):
                self.__dict__[k] = dict_to_obj(v)
            elif isinstance(v, list):
                self.__dict__[k] = [dict_to_obj(item) if isinstance(item, dict) else item for item in v]
            else:
                self.__dict__[k] = v

def dict_to_obj(d):
    return Obj(d)

def get_kind(kind_id, cursor):
    cursor.execute("SELECT kind FROM kind_type WHERE id = %s;", (kind_id,))
    result = cursor.fetchone()
    return result[0] if result else "Unknown"

def flatten_dict_trim(d):
    """
    재귀적으로 nested dict를 평탄화하면서, 각 키를 table.column 형식으로 변환.
    예: {"aka_name": {"name": {"id": 269330, "name": "Chavez, Washington", ... }}} 
    → {"name.id": 269330, "name.name": "Chavez, Washington", ...}
    """
    flat = {}
    def helper(prefix, sub_d):
        for k, v in sub_d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                helper(new_key, v)
            else:
                parts = new_key.split('.')
                if len(parts) >= 2:
                    trimmed_key = f"{parts[-2]}.{parts[-1]}"
                else:
                    trimmed_key = new_key
                flat[trimmed_key] = v
    helper("", d)
    return flat

def format_combined_sentence(template, combined_dict):
    # 템플릿 내의 placeholder의 점(.)을 밑줄(_)로 변환, 그리고 combined_dict의 키도 변경
    new_dict = { key.replace('.', '_'): value for key, value in combined_dict.items() }
    new_template = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace('.', '_') + '}', template)
    class DefaultDict(dict):
        def __missing__(self, key):
            return "null"
    return new_template.format_map(DefaultDict(new_dict))

# 재귀적으로 nested join 결과를 merge하여 각 direct join 결과에 추가
def merge_all_nested(table, rows, nested_joins, cursor):
    merged_list = []
    for row in rows:
        merged = row.copy()
        for nested_table, nested_mapping in nested_joins.items():
            parent_join_col = nested_mapping["join_on"][table]
            nested_join_col = nested_mapping["join_on"][nested_table]
            join_val = row.get(parent_join_col)
            if join_val is None:
                continue
            query = f"SELECT * FROM {nested_table} WHERE {nested_join_col} = %s;"
            cursor.execute(query, (join_val,))
            nested_tuple = cursor.fetchone()
            if not nested_tuple:
                continue
            nested_cols = [desc[0] for desc in cursor.description]
            nested_row = dict(zip(nested_cols, nested_tuple))
            if "kind_id" in nested_row:
                nested_row["kind"] = get_kind(nested_row["kind_id"], cursor)
            # 만약 이 nested_mapping에 further nested joins가 있다면 재귀적으로 merge
            if "nested_joins" in nested_mapping and nested_mapping["nested_joins"]:
                nested_row = merge_all_nested(nested_table, [nested_row], nested_mapping["nested_joins"], cursor)[0]
            # merge: 직접 merge, 즉 키 충돌 시 nested 값이 추가됨
            merged.update({ f"{nested_table}.{k}": v for k, v in nested_row.items() })
        merged_list.append(merged)
    return merged_list

join_mapping = {
    "aka_title": {
        "join_on": { "aka_title": "movie_id", "title": "id" },
        "template": (
            'The alternative title "{aka_title.title}" (alternative title’s ID: {aka_title.id}, associated movie ID: {aka_title.movie_id}, '
            'kind: {aka_title.kind}, IMDB index: {aka_title.imdb_index}, MD5: {aka_title.md5sum}) is associated with this movie. '
            'This version is dated {aka_title.production_year}, as noted: "{aka_title.note}". '
            'The alternative title’s phonetic code is "{aka_title.phonetic_code}".'
        )
    },
    "cast_info": {
        "join_on": { "cast_info": "movie_id", "title": "id" },
        "template": (
            'Cast info: Cast ID {cast_info.id} features person ID {cast_info.person_id} in movie ID {cast_info.movie_id} '
            'with role ID {cast_info.role_id} and character ID {cast_info.person_role_id}. '
            'They were credited in order {cast_info.nr_order}. Additional notes: "{cast_info.note}". '
            'Role type: The role with ID {role_type.id} is classified as "{role_type.role}". '
            'Character: The character "{char_name.name}" (Character ID: {char_name.id}) appears with IMDB index {char_name.imdb_index}. '
            'Phonetic codes: NF="{char_name.name_pcode_nf}", surname="{char_name.surname_pcode}". '
            'MD5 checksum: {char_name.md5sum}. '
            'Alternative name: The alternative name "{aka_name.name}" (aka_name ID: {aka_name.id}, linked to person ID {aka_name.person_id}) '
            'has an IMDB index of {aka_name.imdb_index}, phonetic codes: CF="{aka_name.name_pcode_cf}", '
            'NF="{aka_name.name_pcode_nf}", surname="{aka_name.surname_pcode}". '
            'MD5: {aka_name.aka_md5sum}. '
            'Name: The person with name ID {name.id} is known as "{name.name}", with IMDB index {name.imdb_index}, '
            'gender "{name.gender}". Phonetic codes: CF="{name.name_pcode_cf}", NF="{name.name_pcode_nf}", surname="{name.surname_pcode}". '
            'MD5: {name.md5sum}. '
            'Person info: The person with ID {person_info.person_id} has information categorized as "{person_info.info_type}" '
            '(Info Type ID: {person_info.info_type_id}). Data: "{person_info.info}". Note: "{person_info.note}".'
        ),
        "nested_joins": {
            "role_type": {
                "join_on": { "cast_info": "role_id", "role_type": "id" },
                "template": 'Role type: The role with ID {role_type.id} is classified as "{role_type.role}".'
            },
            "char_name": {
                "join_on": { "cast_info": "person_role_id", "char_name": "id" },
                "template": (
                    'Character: The character "{char_name.name}" (Character ID: {char_name.id}) appears with IMDB index {char_name.imdb_index}. '
                    'Phonetic codes: NF="{char_name.name_pcode_nf}", surname="{char_name.surname_pcode}". '
                    'MD5 checksum: {char_name.md5sum}.'
                )
            },
            "aka_name": {
                "join_on": { "cast_info": "person_id", "aka_name": "id" },
                "template": (
                    'Alternative name: The alternative name "{aka_name.name}" (aka_name ID: {aka_name.id}, linked to person ID {aka_name.person_id}) '
                    'has an IMDB index of {aka_name.imdb_index}, phonetic codes: CF="{aka_name.name_pcode_cf}", '
                    'NF="{aka_name.name_pcode_nf}", surname="{aka_name.surname_pcode}". '
                    'MD5: {aka_name.aka_md5sum}.'
                ),
                "nested_joins": {
                    "name": {
                        "join_on": { "aka_name": "id", "name": "id" },
                        "template": (
                            'Name: The person with name ID {name.id} is known as "{name.name}", with IMDB index {name.imdb_index}, '
                            'gender "{name.gender}". Phonetic codes: CF="{name.name_pcode_cf}", NF="{name.name_pcode_nf}", surname="{name.surname_pcode}". '
                            'MD5: {name.md5sum}.'
                        ),
                        "nested_joins": {
                            "person_info": {
                                "join_on": { "name": "id", "person_info": "person_id" },
                                "template": (
                                    'Person info: The person with ID {person_info.person_id} has information categorized as "{person_info.info_type}" '
                                    '(Info Type ID: {person_info.info_type_id}). Data: "{person_info.info}". Note: "{person_info.note}".'
                                )
                            }
                        }
                    },
                }
            }
        }
    },
    "movie_info": {
        "join_on": { "movie_info": "movie_id", "title": "id" },
        "template": (
            'Movie info: The movie with ID {movie_info.movie_id} contains information categorized as "{info_type.info}" '
            '(Info Type ID: {movie_info.info_type_id}). The recorded data is "{movie_info.info}". Note: "{movie_info.note}". '
        ),
        "nested_joins": {
            "info_type": {
                "join_on": { "movie_info": "info_type_id", "info_type": "id" },
                "template": 'Info type: {info_type.info}.'
            }
        }
    },
    "movie_info_idx": {
        "join_on": { "movie_info_idx": "movie_id", "title": "id" },
        "template": (
            'Indexed movie info: For movie ID {movie_info_idx.movie_id}, the indexed information falls under category "{info_type.info}" '
            '(Info Type ID: {movie_info_idx.info_type_id}). Indexed value: "{movie_info_idx.info}". Note: "{movie_info_idx.note}". '
        ),
        "nested_joins": {
            "info_type": {
                "join_on": { "movie_info_idx": "info_type_id", "info_type": "id" },
                "template": 'Info type: {info_type.info}.'
            }
        }
    },
    "complete_cast": {
        "join_on": { "complete_cast": "movie_id", "title": "id" },
        "template": (
            'Complete cast: The movie with ID {complete_cast.movie_id} has complete cast info recorded. '
            'Subject ID: {complete_cast.subject_id}, Status ID: {complete_cast.status_id}. '
            'Subject kind: {comp_cast_type.subject_kind}, Status: {comp_cast_type.status_kind}.'
        ),
        "nested_joins": {
            "comp_cast_type": {
                "join_on": { "complete_cast": "subject_id", "comp_cast_type": "id" },
                "template": 'Subject kind: {comp_cast_type.subject_kind}, Status: {comp_cast_type.status_kind}.'
            }
        }
    },
    "movie_link": {
        "join_on": { "movie_link": "movie_id", "title": "id" },
        "template": (
            'Movie link: The movie with ID {movie_link.movie_id} is related to the movie with ID {movie_link.linked_movie_id} '
            'through relationship "{link_type.link_type}" (Link Type ID: {movie_link.link_type_id}). '
            'Link type: {link_type.link_type}.'
        ),
        "nested_joins": {
            "link_type": {
                "join_on": { "movie_link": "link_type_id", "link_type": "id" },
                "template": 'Link type: {link_type.link_type}.'
            }
        }
    },
    "movie_keyword": {
        "join_on": { "movie_keyword": "movie_id", "title": "id" },
        "template": (
            'Movie keyword: The movie with ID {movie_keyword.movie_id} is associated with the keyword "{keyword.keyword}" '
            '(Keyword ID: {movie_keyword.keyword_id}, Phonetic Code: "{keyword.phonetic_code}"). '
            'Keyword detail: {keyword.keyword}.'
        ),
        "nested_joins": {
            "keyword": {
                "join_on": { "movie_keyword": "keyword_id", "keyword": "id" },
                "template": 'Keyword detail: {keyword.keyword}.'
            }
        }
    },
    "movie_companies": {
        "join_on": { "movie_companies": "movie_id", "title": "id" },
        "template": (
            'Movie company: The company "{company_name.name}" (Company ID: {movie_companies.company_id}) from {company_name.country_code} '
            'is associated with movie ID {movie_companies.movie_id} as a "{company_type.kind}" company '
            '(Company type ID: {movie_companies.company_type_id}). Phonetic codes: NF="{company_name.name_pcode_nf}", SF="{company_name.name_pcode_sf}". '
            'MD5 checksum: {company_name.md5sum}.'
        ),
        "nested_joins": {
            "company_name": {
                "join_on": { "movie_companies": "company_id", "company_name": "id" },
                "template": 'Company name: {company_name.name}.'
            },
            "company_type": {
                "join_on": { "movie_companies": "company_type_id", "company_type": "id" },
                "template": 'Company type: {company_type.kind}.'
            }
        }
    }
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate unlearning target documents from title table.")
    parser.add_argument("--title_tuple", type=int, default=100, help="Number of title tuples to process")
    args = parser.parse_args()
    
    conn = psycopg2.connect(
        dbname="imdb",
        user="jylee",
        password="YOUR_PW",  # 본인 비밀번호 입력
        host="localhost",
        port="5432"
    )
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT *
        FROM title
        WHERE kind_id = 1
        ORDER BY RANDOM()
        LIMIT {args.title_tuple};
    """)
    title_rows = cursor.fetchall()
    title_columns = [desc[0] for desc in cursor.description]

    output_dir = "unlearning_target"
    os.makedirs(output_dir, exist_ok=True)
    doc_index = 1
    doc_len = 0

    for title_tuple in title_rows:
        title_dict = dict(zip(title_columns, title_tuple))
        if title_dict.get("kind_id"):
            title_dict["kind"] = get_kind(title_dict["kind_id"], cursor)
        else:
            title_dict["kind"] = "Unknown"
        title_sentence_template = (
            'The movie "{title}" (ID: {id}, IMDB index: {imdb_index}) was released as kind {kind} in {production_year}, '
            'with a phonetic code of {phonetic_code} and its MD5 checksum is {md5sum}.'
        )
        title_sentence = title_sentence_template.format(**title_dict)

        direct_join_results = {}
        for table, mapping in join_mapping.items():
            parent_col = mapping["join_on"]["title"]    # 예: title의 "id"
            child_col = mapping["join_on"][table]         # 예: 해당 테이블의 join column
            parent_value = title_dict.get(parent_col)
            if parent_value is None:
                continue
            query = f"SELECT * FROM {table} WHERE {child_col} = %s;"
            cursor.execute(query, (parent_value,))
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            direct_join_results[table] = [dict(zip(cols, row)) for row in rows]

        for table, mapping in join_mapping.items():
            if "nested_joins" in mapping and mapping["nested_joins"]:
                if table in direct_join_results:
                    direct_join_results[table] = merge_all_nested(table, direct_join_results[table], mapping["nested_joins"], cursor)

        document_sentences = [title_sentence]

        for table, rows in direct_join_results.items():
            mapping = join_mapping[table]
            for row in rows:
                flat = flatten_dict_trim({table: row})
                sentence = format_combined_sentence(mapping["template"], flat)
                document_sentences.append(sentence)

        document_text = "\n".join(document_sentences)
        
        output_file = os.path.join(output_dir, f"document_{doc_index}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(document_text)
            
        print(f"Saved document {doc_index} to {output_file}")
        doc_index += 1
        doc_len += len(tokenizer(document_text)["input_ids"])

    print("Total: ", doc_index)
    print("Total len: ", doc_len)
    print(f"Average Docu Len: {doc_len/doc_index}")

    cursor.close()
    conn.close()