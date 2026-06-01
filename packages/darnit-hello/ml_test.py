import torch
import safetensors.torch
from transformers import AutoModelForSequenceClassification

def load_models():
    # Load PyTorch model (EOP/Tampering)
    model1 = torch.load("model.pt")
    
    # Load via safetensors
    tensors = safetensors.torch.load_file("model.safetensors")
    
    # Load via Transformers
    model2 = AutoModelForSequenceClassification.from_pretrained("bert-base-uncased")
