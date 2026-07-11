import yaml
import os


def load_yaml(file_path):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base_dir, file_path)

    with open(full_path, encoding="utf-8") as f:
        return yaml.safe_load(f)



