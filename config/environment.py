import os
import json
from typing import List, Dict, Any, Optional

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
ACTIVE_PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_profile.json")

class EnvironmentProfile:
    def __init__(self, data: Dict[str, Any]):
        self.environment_type: str = data.get("environment_type", "generic")
        self.services: List[str] = data.get("services", [])
        self.critical_components: List[str] = data.get("critical_components", [])
        self.error_categories: List[str] = data.get("error_categories", [])
        self.business_entities: List[str] = data.get("business_entities", [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment_type": self.environment_type,
            "services": self.services,
            "critical_components": self.critical_components,
            "error_categories": self.error_categories,
            "business_entities": self.business_entities
        }

def get_available_profiles() -> List[str]:
    if not os.path.exists(PROFILE_DIR):
        return ["generic"]
    profiles = []
    for file in os.listdir(PROFILE_DIR):
        if file.endswith(".json"):
            profiles.append(file[:-5])
    return profiles

def get_active_profile_name() -> str:
    if os.path.exists(ACTIVE_PROFILE_FILE):
        try:
            with open(ACTIVE_PROFILE_FILE, "r") as f:
                data = json.load(f)
                return data.get("active_profile", "ecommerce")
        except Exception:
            pass
    return "ecommerce"

def set_active_profile_name(profile_name: str) -> bool:
    profiles = get_available_profiles()
    if profile_name not in profiles:
        return False
    try:
        os.makedirs(os.path.dirname(ACTIVE_PROFILE_FILE), exist_ok=True)
        with open(ACTIVE_PROFILE_FILE, "w") as f:
            json.dump({"active_profile": profile_name}, f, indent=2)
        return True
    except Exception:
        return False

def load_profile(profile_name: str) -> EnvironmentProfile:
    file_path = os.path.join(PROFILE_DIR, f"{profile_name}.json")
    if not os.path.exists(file_path):
        return EnvironmentProfile({"environment_type": profile_name})
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            return EnvironmentProfile(data)
    except Exception:
        return EnvironmentProfile({"environment_type": profile_name})

def get_active_profile() -> EnvironmentProfile:
    name = get_active_profile_name()
    return load_profile(name)
