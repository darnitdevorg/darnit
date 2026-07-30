import safetensors.torch
import torch
from transformers import AutoModelForSequenceClassification


def load_models():
    # Load PyTorch model (EOP/Tampering)
    torch.load("model.pt")

    # Load via safetensors
    safetensors.torch.load_file("model.safetensors")

    # Load via Transformers
    AutoModelForSequenceClassification.from_pretrained("bert-base-uncased")
