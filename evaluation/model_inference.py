import json
import os
import torch
import psycopg2

from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm
from rouge_score import rouge_scorer
from nl_question_construction.sqlToNL import generate_nl_qa_pair
from utils.constants import FINETUNED_MODEL_DIR, UNLEARNED_MODEL_DIR
conn = psycopg2.connect(
    dbname="postgres",
    user="jylee",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

def generate_text(model, tokenizer, prompt, max_new_tokens=200, max_retries=11):
    model.eval()
    
    for attempt in range(max_retries):
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        input_ids = inputs["input_ids"]

        with torch.no_grad():
            gen_outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )

        generated_text = tokenizer.decode(gen_outputs[0][len(input_ids[0]):], skip_special_tokens=True).strip()

        # Only return if non-trivial text is generated
        if len(generated_text) >= 3:
            return generated_text

    return generated_text  # Return last attempt even if still empty

def modelInference(model_path, model_id, query_file_path, output_dir):
    data_list = []
    
    with open(query_file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data_list.append(json.loads(line))
    
    query_list = []
    answer_list = []
    generated_text_list = []
    
    for data in data_list:
        sql = data.get("sql", "")
        
        if sql:
            try:
                cursor.execute(sql)
                rows = cursor.fetchall()
                if len(rows) == 1 and len(rows[0]) == 1:
                    answer = str(rows[0][0])
                else:
                    answer = ", ".join([str(item) for row in rows for item in row])
            except Exception as e:
                print(f"SQL execution error: {e}")
                answer = ""
        else:
            answer = ""

        #query, answer = generate_nl_qa_pair(sql, answer)
        query = data.get("nl_query", "")
        answer = data.get("answer", "")

        query_list.append(query)
        answer_list.append(answer)

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        #model_id, 
        torch_dtype=torch.float16, 
        trust_remote_code = True,
        #cache_dir="/home/jylee/SUN/pretrained_model",
        device_map='auto',
    )
    
    total_rouge1 = 0
    total_rouge2 = 0
    total_rougeL = 0

    for idx, query in tqdm(enumerate(query_list)):
        prompt = f"Q: {query}\nA:"
        gold_answer = answer_list[idx]
        generated_text = generate_text(model, tokenizer, prompt)
        generated_text_list.append(generated_text)
        
        scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
        scores = scorer.score(generated_text, gold_answer)
        
        total_rougeL += scores['rougeL'].fmeasure
        total_rouge1 += scores['rouge1'].fmeasure
        total_rouge2 += scores['rouge2'].fmeasure
        
        print(f"Query: \n{prompt}")
        print(f"Gold Answer: \n{gold_answer}")
        print(f"Generated Answer: \n{generated_text}")
        
        #print(f"RougeL: {scores['rougeL'].fmeasure}")
        
    
    average_rouge1 = total_rouge1 / len(query_list)
    average_rouge2 = total_rouge2 / len(query_list)
    average_rougeL = total_rougeL / len(query_list)
    
    with open(output_dir, "w", encoding="utf-8") as f:
        f.write(f"Average Rouge1: {average_rouge1}\n")
        f.write(f"Average Rouge2: {average_rouge2}\n")
        f.write(f"Average RougeL: {average_rougeL}\n")
        
        for idx, query in enumerate(query_list):
            json_line = {
                "query_id": idx,
                'Rouge1': scores['rouge1'].fmeasure,
                'Rouge2': scores['rouge2'].fmeasure,
                'RougeL': scores['rougeL'].fmeasure,
                "query": query,
                "gold_answer": answer_list[idx],
                "generated_answer": generated_text_list[idx]
            }
            f.write(json.dumps(json_line) + "\n")

if __name__ == '__main__':
    model_path = '/home/jylee/SUN/finetuned_model/retrained_model/ft_epoch20_lr1e-05_wd0.01/checkpoint-179'
    model_id = "meta-llama/Llama-2-7b-hf"
    
    query_file_path = '/home/jylee/SUN/job_results/NL_queries/simple_qa.jsonl'
    output_dir = '/home/jylee/SUN/job_results/NL_queries/quality_check_ul__'
    
    modelInference(model_path, model_id, query_file_path, output_dir)