from utils.dataloader import CustomUnlearningTrainer, custom_data_collator, ChunkedTextDataset
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig, set_seed

import hydra 
import transformers
import os
import json
from pathlib import Path
from utils.utils import get_model_identifiers_from_yaml

def find_all_linear_names(model):
    cls = torch.nn.Linear
    lora_module_names = set()
    for name, module in model.named_modules():
        if isinstance(module, cls):
            names = name.split('.')
            lora_module_names.add(names[0] if len(names) == 1 else names[-1])
    if 'lm_head' in lora_module_names: # needed for 16-bit
        lora_module_names.remove('lm_head')
    return list(lora_module_names)

def print_trainable_parameters(model):
    trainable_params = 0
    all_param = 0
    for _, param in model.named_parameters():
        all_param += param.numel()
        if param.requires_grad:
            trainable_params += param.numel()
    print(
        f"trainable params: {trainable_params} || all params: {all_param} || trainable%: {100 * trainable_params / all_param}"
    )

@hydra.main(version_base=None, config_path="config", config_name="forget")
def main(cfg):
    if os.environ.get('LOCAL_RANK') is not None:
        local_rank = int(os.environ.get('LOCAL_RANK', '0'))
    set_seed(cfg.seed)
    os.environ["WANDB_DISABLED"] = "true"
    model_cfg = get_model_identifiers_from_yaml(cfg.model_family)
    model_id = model_cfg["hf_key"]

    Path(cfg.save_dir).mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token

    file_path = cfg.data_path
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_title = ['Timeliner']  # Can be extended
    target_texts = []
    retained_texts = []
    
    for example in data:
        title = example.get("title", [{}])
        if title in target_title:
            target_texts.append(example["dict_description"])
        else:
            retained_texts.append(example["dict_description"])
    
    total_texts = target_texts + retained_texts
    
    def count_total_tokens(texts):
        return sum(len(tokenizer.encode(text)) for text in texts)
    
    total_tokens = count_total_tokens(total_texts)
    target_tokens = count_total_tokens(target_texts)
    
    print(f"Total tokens in dataset: {total_tokens}")
    print(f"Tokens in unlearning targets: {target_tokens}")
    print(f"Ratio: {target_tokens / total_tokens:.2%}")
    
    # Only use unlearning target data
    texts = target_texts

    max_length = 512
    torch_format_dataset = ChunkedTextDataset(
        texts=texts, 
        tokenizer=tokenizer, 
        max_length=max_length, 
        stride=256
    )

    batch_size = cfg.batch_size
    gradient_accumulation_steps = cfg.gradient_accumulation_steps

    num_devices = int(os.environ.get('WORLD_SIZE', 1))
    print(f"num_devices: {num_devices}")

    max_steps = int(cfg.num_epochs*len(torch_format_dataset))//(batch_size*gradient_accumulation_steps*num_devices)

    print(f"max_steps: {max_steps}")
    training_args = transformers.TrainingArguments(
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            warmup_steps=max(1, max_steps//cfg.num_epochs),
            max_steps=max_steps,
            learning_rate=cfg.lr,
            bf16=True,
            bf16_full_eval=True,
            logging_steps=max(1,max_steps//20),
            logging_dir=f'{cfg.save_dir}/logs',
            output_dir=cfg.save_dir,
            optim="paged_adamw_32bit",
            save_steps=max_steps,
            save_only_model=True,
            ddp_find_unused_parameters= False,
            evaluation_strategy="no",
            deepspeed='config/ds_config.json',
            weight_decay = cfg.weight_decay,
            seed = cfg.seed,
        )

    model = AutoModelForCausalLM.from_pretrained(
        cfg.model_path, 
        use_flash_attention_2=model_cfg["flash_attention2"]=="true", 
        torch_dtype=torch.bfloat16, 
        trust_remote_code = True,
    )
    
    model.generation_config.do_sample = True

    if model_cfg["gradient_checkpointing"] == "true":
        model.gradient_checkpointing_enable()

    trainer = CustomUnlearningTrainer(
        model=model,
        train_dataset=torch_format_dataset,
        eval_dataset=torch_format_dataset,
        args=training_args,
        data_collator=custom_data_collator,
        forget_loss = cfg.forget_loss,
    )
    model.config.use_cache = False  # silence the warnings. Please re-enable for inference!
    trainer.train()

    model.save_pretrained(cfg.save_dir)
    tokenizer.save_pretrained(cfg.save_dir)

if __name__ == "__main__":
    main()
