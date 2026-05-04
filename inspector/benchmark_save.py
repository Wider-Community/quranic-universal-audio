import time
import cProfile
import pstats
from services.save import save_seg_data
from services.data_loader import load_detailed

def run_benchmark():
    reciter = "bandar_balilah"
    entries = load_detailed(reciter)
    
    if not entries:
        print("No entries found.")
        return
        
    chapter = int(entries[0]["ref"].split(":")[0])
    matching = [e for e in entries if int(e["ref"].split(":")[0]) == chapter]
    
    if not matching:
        print("No matching chapter found.")
        return

    print(f"Benchmarking saving for reciter: {reciter}, chapter: {chapter}, with {len(entries)} total entries and {len(matching)} chapter entries.")
    
    # Simulate a dummy update payload (a patch save)
    updates = {
        "full_replace": False,
        "segments": [
            {
                "index": 0, # assuming at least 1 segment
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
    
    print(f"Result: {res}")
    print(f"Time taken: {end - start:.4f} seconds")

if __name__ == "__main__":
    pr = cProfile.Profile()
    pr.enable()
    run_benchmark()
    pr.disable()
    stats = pstats.Stats(pr)
    stats.sort_stats('cumtime').print_stats(40)
