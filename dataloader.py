import torch
from transformers import Trainer
from torch.utils.data import Dataset

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
    def __init__(self, texts, tokenizer, max_length=512, stride=256, loss_type='idk'):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.stride = stride
        self.samples = []

        total_token = len(tokenizer.encode("".join(texts)))
        print(f"Total Training Token: {total_token}")

        for text in texts:
            text = '<|startofdocument|>' + text + '<|endoftext|>\n'
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