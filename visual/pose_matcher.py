import numpy as np
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class PoseMatcher:
    """
    Matches a stream of 21 hand landmarks against a set of saved templates.
    Uses wrist-relative normalization and scaled Euclidean distance.
    Templates store both the signature vector and the associated action/params.
    """

    def __init__(self, threshold: float = 0.5):
        self.templates: Dict[str, Dict] = {} # name -> {vector: np.ndarray, action: str, params: dict}
        self.threshold = threshold

    def add_template(self, name: str, landmarks: List, action: str = "none", params: dict = None):
        """
        Processes and stores a normalized landmark vector with metadata.
        """
        vector = self._normalize(landmarks)
        self.templates[name] = {
            "vector": vector,
            "action": action,
            "params": params or {}
        }
        logger.info(f"Added custom pose template: {name} (Action: {action})")

    def match(self, landmarks: List) -> Optional[str]:
        """
        Compares current landmarks to all templates.
        Returns the name of the best matching pose, or None.
        """
        if not self.templates:
            return None

        current_vector = self._normalize(landmarks)
        
        best_match = None
        min_dist = float('inf')

        for name, data in self.templates.items():
            template_vector = data["vector"]
            dist = np.linalg.norm(current_vector - template_vector)
            if dist < min_dist:
                min_dist = dist
                best_match = name

        if min_dist < self.threshold:
            return best_match
        return None

    def get_action_for_pose(self, name: str) -> Optional[Dict]:
        """Returns the action metadata for a matched pose."""
        return self.templates.get(name)

    def _normalize(self, landmarks) -> np.ndarray:
        """
        1. Translate wrist to (0,0,0)
        2. Scale to unit bounding box
        3. Flatten to 63-value vector
        """
        # Convert landmarks to np array: handle both dicts and MediaPipe objects
        if hasattr(landmarks[0], 'x'):
            pts = np.array([[lm.x, lm.y, lm.z] for lm in landmarks])
        else:
            pts = np.array([[lm['x'], lm['y'], lm['z']] for lm in landmarks])
        
        # 1. Translate wrist (index 0) to origin
        wrist = pts[0]
        pts = pts - wrist
        
        # 2. Scale by max distance from wrist
        max_dist = np.max(np.linalg.norm(pts, axis=1))
        if max_dist > 0:
            pts = pts / max_dist
            
        return pts.flatten()

    def save_templates(self, filepath: str):
        import json
        out_data = {}
        for name, data in self.templates.items():
            out_data[name] = {
                "vector": data["vector"].tolist(),
                "action": data["action"],
                "params": data["params"]
            }
        with open(filepath, 'w') as f:
            json.dump(out_data, f, indent=2)

    def load_templates(self, filepath: str):
        import json
        import os
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                self.templates = {}
                for name, d in data.items():
                    self.templates[name] = {
                        "vector": np.array(d["vector"]),
                        "action": d.get("action", "none"),
                        "params": d.get("params", {})
                    }
                logger.info(f"Loaded {len(self.templates)} custom poses from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load custom poses: {e}")
