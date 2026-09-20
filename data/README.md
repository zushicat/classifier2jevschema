### An empty directory for potentional usage of data files.    
Defined in Dockerfile as
```
DATA_DIR=/app/data
```
and is simply kept for convenience. (You can remove this in case you don't need any data directory within the container.)    
    
Example usage (anywhere in /src) could be something like this
```
import json
import os
from typing import Any, Dict

DATA_DIR = os.environ["DATA_DIR"]


def read_json_file(file_path: str) -> Dict[str, Any]:
    with open(f"{DATA_DIR}/{file_path}", "r") as f:
        return json.load(f)

if __name__ == "__main__":
    print(json.dumps(read_json_file("my-example-file.json"), indent=2))
```