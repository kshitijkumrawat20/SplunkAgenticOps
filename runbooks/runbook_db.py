import os
from typing import List, Dict, Any

def search_runbooks(query: str) -> List[Dict[str, Any]]:
    """
    Searches markdown runbooks in the runbooks/ directory recursively for keywords.
    Returns a list of matching sections.
    """
    runbooks_dir = os.path.dirname(os.path.abspath(__file__))
    matches = []
    
    # Extract keywords from search query
    keywords = [kw.strip().lower() for kw in query.replace("-", " ").split() if len(kw.strip()) > 2]
    if not keywords:
        return []

    for root, dirs, files in os.walk(runbooks_dir):
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        
                    content_lower = content.lower()
                    # Check if any keyword matches content
                    if any(kw in content_lower for kw in keywords):
                        # Find specific section or return whole content
                        matches.append({
                            "runbook": file,
                            "content": content
                        })
                except Exception as e:
                    # Log or ignore
                    pass
                    
    # De-duplicate by runbook file name to prevent double matches from legacy root files
    seen = set()
    deduped_matches = []
    for m in matches:
        if m["runbook"] not in seen:
            seen.add(m["runbook"])
            deduped_matches.append(m)
            
    return deduped_matches
