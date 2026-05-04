import time
from services.save import save_seg_data
from services.data_loader import load_detailed

def run_benchmark():
    reciter = "bandar_balilah"
    entries = load_detailed(reciter)
    
    chapter = int(entries[0]["ref"].split(":")[0])
    
    updates = {
        "full_replace": False,
        "segments": [
            {
                "index": 0,
                "matched_ref": "1:1:1",
                "matched_text": "بسم",
                "confidence": 0.99
            }
        ],
        "operations": [
            {
                "type": "edit_reference",
                "command": {"type": "edit_reference"},
                "patch": {
                    "before": [],
                    "after": [],
                    "removedIds": [],
                    "insertedIds": [],
                    "affectedChapterIds": []
                }
            }
        ]
    }
    
    start = time.time()
    res = save_seg_data(reciter, chapter, updates)
    end = time.time()
    
    print(f"Time taken without profiling: {end - start:.4f} seconds")

if __name__ == "__main__":
    run_benchmark()
