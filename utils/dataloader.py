import torch
import json
import datasets
import yaml
import numpy as np

from transformers import Trainer
from torch.utils.data import Dataset

def convert_raw_data_to_model_format(tokenizer, max_length,  question, answer, model_configs):
    question_start_token, question_end_token, answer_token = model_configs['question_start_tag'], model_configs['question_end_tag'], model_configs['answer_tag']
    new_question = question_start_token + question + question_end_token
    new_answer = answer_token + answer
    full_text = new_question + new_answer
    num_question_tokens = len(tokenizer.tokenize(new_question, add_special_tokens=True))

    encoded = tokenizer(
        full_text, 
        add_special_tokens=True, 
        max_length=max_length, 
        truncation=True, 
    )
    pad_length = max_length - len(encoded.input_ids)
    pad_input_ids = encoded['input_ids'] + [tokenizer.eos_token_id] * pad_length
    pad_attention_mask = encoded['attention_mask'] + [0] * pad_length
    if len(encoded.input_ids) == max_length:
        label = encoded.input_ids
    else:
        label = encoded['input_ids'] + [tokenizer.eos_token_id] + [-100] * (pad_length-1)

    #change label to -100 for question tokens
    for i in range(num_question_tokens): label[i] = -100

    return torch.tensor(pad_input_ids),torch.tensor(label),torch.tensor(pad_attention_mask)

class CustomTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False):
        outputs = model(**inputs)
        loss = outputs.loss
        if loss.dim() > 0:
            loss = loss.mean()
        return (loss, outputs) if return_outputs else loss
    
    def prediction_step(self, model, inputs, prediction_loss_only: bool, ignore_keys=None):
        input_ids, labels, attention_mask = inputs
        # forward pass
        with torch.no_grad():
            outputs = model(input_ids,labels=labels, attention_mask=attention_mask)
            logits = outputs.logits
            loss = outputs.loss
        return (loss, logits, labels)

class CustomUnlearningTrainer(Trainer):
    def __init__(self, *args, **kwargs):
        self.loss_type = kwargs.pop("forget_loss")
        #self.original_model = kwargs.pop("original_model")
        super().__init__(*args, **kwargs)
        
    def compute_loss(self, model, inputs, return_outputs=False):
        if self.loss_type == "grad_ascent":
            outputs = model(**inputs)
            loss = outputs.loss
            if loss.dim() > 0:
                loss = loss.mean()
            loss = -loss
            return (loss, outputs) if return_outputs else loss
    
    def prediction_step(self, model, inputs, prediction_loss_only: bool, ignore_keys=None):
        input_ids, labels, attention_mask = inputs
        # forward pass
        with torch.no_grad():
            outputs = model(input_ids,labels=labels, attention_mask=attention_mask)
            logits = outputs.logits
            loss = outputs.loss
        return (loss, logits, labels)    

def custom_data_collator(samples):
    # samples: List[Dict[str, torch.Tensor]] 형태
    # => batch 단위로 합쳐서 다시 Dict[str, torch.Tensor] 형태로 반환
    input_ids = torch.stack([s["input_ids"] for s in samples])
    labels = torch.stack([s["labels"] for s in samples])
    attention_mask = torch.stack([s["attention_mask"] for s in samples])
    return {
        "input_ids": input_ids,
        "labels": labels,
        "attention_mask": attention_mask,
    }
        
class ChunkedTextDataset(Dataset):
    def __init__(self, forget_data_path, retain_data_path, tokenizer, max_length=512, stride=256, loss_type='idk'):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.stride = stride
        self.samples = []

        with open(forget_data_path, "r", encoding="utf-8") as f:
            forget_data = json.load(f)
        
        with open(retain_data_path, "r", encoding="utf-8") as f:
            retain_data = json.load(f)

        self.forget_texts = [text for author, text in forget_data.items()]
        self.retain_texts = [text for author, text in retain_data.items()]

        total_token = len(tokenizer.encode("\n\n".join(self.forget_texts + self.retain_texts)))
        print(f"Total Training Token: {total_token}")

        for text in self.forget_texts + self.retain_texts:
            text = text.strip()
            tokens = tokenizer(text, return_tensors="pt")["input_ids"].squeeze(0)
            token_len = tokens.size(0)

            for i in range(0, token_len, stride):
                chunk = tokens[i : i + max_length]
                if chunk.size(0) < max_length:
                    padding = torch.full(
                        (max_length - chunk.size(0),),
                        tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
                    )
                    chunk = torch.cat([chunk, padding], dim=0)
                self.samples.append(chunk)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        input_ids = self.samples[idx]
        labels = input_ids.clone()
        attention_mask = (input_ids != self.tokenizer.pad_token_id).long()
        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": attention_mask,
        }
        
class TextDatasetQA(Dataset):
    def __init__(self, data_path, tokenizer, model_family, max_length=512, split = None):
        super(TextDatasetQA, self).__init__()
        self.tokenizer = tokenizer
        self.max_length = max_length
        
        dataset = datasets.load_dataset(data_path, split)["train"]
        indexing = np.arange(len(dataset))
        self.data = dataset.add_column('index', indexing)
        
        model_configs = {}
        with open("/home/jylee/SUN/config/model_config.yaml", "r") as f:
            model_configs = yaml.load(f, Loader=yaml.FullLoader)
        self.model_configs = model_configs[model_family]

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        question = self.data[idx]['question']
        answer = self.data[idx]['answer']

        converted_data = convert_raw_data_to_model_format(self.tokenizer, self.max_length, question, answer, self.model_configs)

        return {
            "input_ids": converted_data[0],
            "labels": converted_data[1],
            "attention_mask": converted_data[2],
        }