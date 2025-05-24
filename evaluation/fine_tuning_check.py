import torch
import json

from rouge_score import rouge_scorer
from utils.dataloader import ChunkedTextDataset
from transformers import AutoTokenizer, AutoModelForCausalLM

PART_PROMPT_SIZE = 50

scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)

def compute_rouge(reference, hypothesis):
    scores = scorer.score(reference, hypothesis)
    return scores['rougeL'].fmeasure

def extract_prompts_from_dataset(dataset, tokenizer, num_prompts=-1):
    prompts = []
    part_prompts = []
    if num_prompts == -1:
        num_prompts = len(dataset)
    for i in range(min(num_prompts, len(dataset))):
        input_ids = dataset[i]['input_ids']
        part_input_ids = dataset[i]["input_ids"][:PART_PROMPT_SIZE]
        prompt_text = tokenizer.decode(input_ids, skip_special_tokens=True)
        part_prompt_text = tokenizer.decode(part_input_ids, skip_special_tokens=True)
        prompts.append(prompt_text)
        part_prompts.append(part_prompt_text)

    return prompts, part_prompts

def compute_perplexity(model, tokenizer, input_text, target_position=-1):
    model.eval()
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)
    input_ids = inputs["input_ids"]
    
    if target_position == -1:
        target_position = input_ids.shape[1] - 1
        
    # labels = torch.full_like(input_ids, -100)
    # labels[0, target_position] = input_ids[0, target_position]
    
    labels = input_ids.clone()
    
    with torch.no_grad():
        outputs = model(**inputs, labels=labels)
        loss = outputs.loss
        perplexity = torch.exp(loss)
    
    return perplexity.item()

def generate_text(model, tokenizer, prompt, gold_prompt, max_new_tokens=200):
    model.eval()
    
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_ids = inputs["input_ids"]
    
    gold_inputs = tokenizer(gold_prompt, return_tensors="pt").to(model.device)
    gold_input_ids = gold_inputs["input_ids"]

    with torch.no_grad():
        gen_outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=0,
            top_p=1,
        )
        
        outputs = model(**gold_inputs, labels=gold_input_ids)
        loss = outputs.loss
        perplexity = torch.exp(loss)

    generated_text = tokenizer.decode(gen_outputs[0][len(input_ids[0]):], skip_special_tokens=True)
    return generated_text, perplexity.item()

def evaluate_models(original_model_path, finetuned_model_path, dataset, tokenizer, num_samples=5, cache_dir="/home/jylee/SUN/pretrained_model"):
    original_model = AutoModelForCausalLM.from_pretrained(
        original_model_path, 
        use_flash_attention_2=False, 
        torch_dtype=torch.bfloat16, 
        cache_dir=cache_dir,
        device_map="auto"
    )

    finetuned_model = AutoModelForCausalLM.from_pretrained(
        finetuned_model_path, 
        use_flash_attention_2=False, 
        torch_dtype=torch.bfloat16,
        device_map="auto"
    )

    results = {
        'Avg PPL': {
            'Original': 0,
            'Fine_tuned' : 0  
        },
        # 'Avg ROUGE': {
        #     'Original': 0,
        #     'Fine_tuned' : 0
        # },
        'PPL': {
            'Original': [],
            'Fine_tuned' : []   
        },
        # 'ROUGE': {
        #     'Original': [],
        #     'Fine_tuned' : []   
        # },
    }

    prompts, part_prompts = extract_prompts_from_dataset(dataset, tokenizer, num_samples)

    for i, full_text in enumerate(prompts):
        print(f"\n=== Prompt {i+1} ===")
        
        original_ppl = compute_perplexity(original_model, tokenizer, full_text)
        finetuned_ppl = compute_perplexity(finetuned_model, tokenizer, full_text)
        
        print(f"Original Model PPL: {original_ppl:.4f}")
        print(f"Fine-tuned Model PPL: {finetuned_ppl:.4f}")
        
        results['PPL']['Original'].append(original_ppl)
        results['PPL']['Fine_tuned'].append(finetuned_ppl)
    
    print("Average Original PPL: ", sum(results['PPL']['Original'])/len(results['PPL']['Original']))
    print("Average Fine-tuned PPL: ", sum(results['PPL']['Fine_tuned'])/len(results['PPL']['Fine_tuned']))
    
    results['Avg PPL']['Original'] = sum(results['PPL']['Original'])/len(results['PPL']['Original'])
    results['Avg PPL']['Fine_tuned'] = sum(results['PPL']['Fine_tuned'])/len(results['PPL']['Fine_tuned'])

    # for i, prompt in enumerate(part_prompts):
    #     print(f"\n=== Prompt {i+1} ===")
    #     # print(f"Prompt: {prompt}")
        
    #     gold_prompt = prompts[i]

    #     original_text, original_ppl = generate_text(original_model, tokenizer, prompt, gold_prompt)
    #     finetuned_text, finetuned_ppl = generate_text(finetuned_model, tokenizer, prompt, gold_prompt)
        
    #     tokenized_gold_prompt = tokenizer(gold_prompt, return_tensors="pt")
    #     gold_gen_text = tokenizer.decode(tokenized_gold_prompt['input_ids'][0][50:250], skip_special_tokens=True)
        
    #     original_rouge = compute_rouge(gold_gen_text, original_text)
    #     finetuned_rouge = compute_rouge(gold_gen_text, finetuned_text)
        
    #     print(f"Original Model PPL: {original_ppl:.4f}")
    #     print(f"Fine-tuned Model PPL: {finetuned_ppl:.4f}")
        
    #     results['PPL']['Original'].append(original_ppl)
    #     results['PPL']['Fine_tuned'].append(finetuned_ppl)

    #     print(f"Original Model ROUGE: {original_rouge}")
    #     print(f"Fine-tuned Model ROUGE: {finetuned_rouge}")
        
    #     results['ROUGE']['Original'].append(original_rouge)
    #     results['ROUGE']['Fine_tuned'].append(finetuned_rouge)
        
    # results['Avg ROUGE']['Original'] = sum(results['ROUGE']['Original'])/len(results['ROUGE']['Original'])
    # results['Avg ROUGE']['Fine_tuned'] = sum(results['ROUGE']['Fine_tuned'])/len(results['ROUGE']['Fine_tuned'])

    return results
    
def main():
    original_model_path = "meta-llama/Llama-2-7b-hf"

    finetuned_model_path = "/home/jylee/SUN/finetuned_model/retrained_model/ft_epoch20_lr1e-05_wd0.01/checkpoint-37"

    tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-2-7b-hf")
    tokenizer.pad_token = tokenizer.eos_token
    
    file_path = "/home/jylee/SUN/unlearning_target/text/text_descriptions_adaptive_73.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    texts = [example["dict_description"] for example in data]

    max_length = 512
    dataset = ChunkedTextDataset(
        texts=texts, 
        tokenizer=tokenizer, 
        max_length=max_length, 
        stride=256
    )

    result = evaluate_models(original_model_path, finetuned_model_path, dataset, tokenizer, num_samples=-1)
    
    output_file = '/home/jylee/SUN/finetuning_check.json'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"\n✅ 결과가 저장되었습니다: {output_file}")

if __name__ == "__main__":
    main()