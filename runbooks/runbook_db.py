import os
from typing import List, Dict, Any

def search_runbooks(query: str) -> List[Dict[str, Any]]:
    """
    Searches markdown runbooks in the runbooks/ directory for keywords.
    Returns a list of matching sections.
    """
    runbooks_dir = os.path.dirname(os.path.abspath(__file__))
    matches = []
    
    # Extract keywords from search query
    keywords = [kw.strip().lower() for kw in query.replace("-", " ").split() if len(kw.strip()) > 2]
    if not keywords:
        return []

    for file in os.listdir(runbooks_dir):
        if file.endswith(".md"):
            filepath = os.path.join(runbooks_dir, file)
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
                
    return matches
