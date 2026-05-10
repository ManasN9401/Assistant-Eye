import numpy as np
import time
from typing import List, Optional

class ASLRecognizer:
    """
    Heuristic-based ASL letter recognition.
    Matches hand landmarks to ASL letters based on finger extensions and relative positions.
    """
    
    @staticmethod
    def _dist(a, b):
        return np.linalg.norm(np.array([a.x - b.x, a.y - b.y]))

    @staticmethod
    def recognize(lms) -> Optional[str]:
        if not lms: return None
        
        # ─── 1. EXTENSION ANALYSIS ───
        # Using PIP as reference for "curled" vs "extended"
        ext = [
            lms[8].y < lms[6].y,   # Index
            lms[12].y < lms[10].y, # Middle
            lms[16].y < lms[14].y, # Ring
            lms[20].y < lms[18].y  # Pinky
        ]
        
        # ─── 2. UTILITIES ───
        def d(i, j): return ASLRecognizer._dist(lms[i], lms[j])
        
        # ─── 3. THUMB STATE ───
        # Thumb is out if x is away from index base
        thumb_out = abs(lms[4].x - lms[5].x) > 0.07
        thumb_up = lms[4].y < lms[2].y - 0.04
        
        # ─── 4. RECOGNITION LOGIC ───

        # B: All extended and together
        if all(ext) and d(8, 12) < 0.05: return "B"
        
        # F: Index/Thumb touch, others extended
        if d(4, 8) < 0.06 and all(ext[1:]): return "F"
        
        # L: Index/Thumb extended
        if ext[0] and not any(ext[1:]) and thumb_out and thumb_up: return "L"
        
        # I / J: Pinky extended
        if ext[3] and not any(ext[:3]):
            return "I_CANDIDATE" # J handled in Translator

        # Y: Thumb and Pinky
        if ext[3] and thumb_out and not any(ext[:3]): return "Y"

        # W: Index, Middle, Ring
        if ext[0] and ext[1] and ext[2] and not ext[3]: return "W"

        # V, U, R, K, H, G, P, Q
        # These depend heavily on orientation (flat vs vertical)
        is_flat = abs(lms[8].y - lms[5].y) < 0.08 # Hand pointing "forward"
        
        # Two fingers (Index & Middle)
        if ext[0] and ext[1] and not ext[2] and not ext[3]:
            if is_flat:
                # P (Down) vs H (Across)
                if lms[8].y > lms[0].y + 0.1: return "P"
                return "H"
            else:
                # V, U, R, K
                if lms[8].x > lms[12].x + 0.02: return "R" # Crossed
                if d(8, 12) < 0.04: return "U"
                if d(4, 10) < 0.06: return "K"
                return "V"

        # One finger (Index)
        if ext[0] and not any(ext[1:]):
            if is_flat:
                # Q (Down) vs G (Across)
                if lms[8].y > lms[0].y + 0.1: return "Q"
                return "G"
            else:
                # D or Z
                return "D_CANDIDATE" # Z handled in Translator

        # X: Index Hooked
        if lms[8].y > lms[6].y and lms[8].y < lms[5].y + 0.02 and not any(ext[1:]):
            return "X"

        # C / O: Curved
        if not any(ext):
             dist_tips_thumb = sum(d(i, 4) for i in [8, 12, 16, 20]) / 4
             if dist_tips_thumb < 0.07: return "O"
             if dist_tips_thumb < 0.15 and d(8, 20) > 0.08: return "C"

        # Fists (A, S, T, N, M, E)
        if not any(ext):
            # E: Tips are tight but not covering thumb
            if all(lms[i].y > lms[i-1].y for i in [8, 12, 16, 20]) and d(4, 8) > 0.1:
                 return "E"
            
            # S: Thumb clearly over the middle/index fingers
            if d(4, 10) < 0.055 or d(4, 9) < 0.055: return "S"
            
            # T, N, M: Thumb tucked under specific fingers
            if d(4, 6) < 0.05: return "T"  # Under Index PIP
            if d(4, 10) < 0.05: return "N" # Under Middle PIP
            if d(4, 14) < 0.05: return "M" # Under Ring PIP
            
            # A: Default for fist (thumb on side)
            return "A"

        return None

class SignTranslator:
    """
    Accumulates letters into words and words into sentences.
    Handles timing and stability.
    """
    def __init__(self):
        self.current_letter = None
        self.letter_start_time = 0
        self.confirm_duration = 0.6 # seconds to hold a sign
        
        self.current_word = ""
        self.translation = ""
        self.last_action_time = 0
        self.idle_timeout = 3.0 # Clear current word after 3s of nothing
        self.paused = False
        
        # Movement tracking for 'Z'
        self.pos_buffer = [] # list of (x, y, t)
        
    def update(self, detected_letter: Optional[str], tip_pos: Optional[tuple] = None, confirm_duration: float = 0.6) -> dict:
        self.confirm_duration = confirm_duration
        now = time.time()
        
        if self.paused:
            return {"event": "paused", "letter": detected_letter, "word": self.current_word, "full": self.translation}
        
        # Track movement for Z and J
        if tip_pos:
            self.pos_buffer.append((*tip_pos, now))
            if len(self.pos_buffer) > 40: self.pos_buffer.pop(0)
            
            if len(self.pos_buffer) > 10:
                xs = [p[0] for p in self.pos_buffer]
                ys = [p[1] for p in self.pos_buffer]
                
                # Z detection (Zig-Zag in X while index is up)
                if detected_letter == "D_CANDIDATE":
                    dx = np.diff(xs)
                    sign_changes = np.where(np.diff(np.sign(dx[np.abs(dx) > 0.005])))[0]
                    if len(sign_changes) >= 2:
                        detected_letter = "Z"
                        self.pos_buffer = []
                
                # J detection (Curve in Y while pinky is up)
                if detected_letter == "I_CANDIDATE":
                    dy = np.diff(ys)
                    # Look for downward movement then upward hook
                    if any(dy > 0.02) and any(dy < -0.01) and xs[-1] < xs[0] - 0.03:
                        detected_letter = "J"
                        self.pos_buffer = []
        else:
            self.pos_buffer = []

        # Fallbacks for candidates
        if detected_letter == "D_CANDIDATE": detected_letter = "D"
        if detected_letter == "I_CANDIDATE": detected_letter = "I"

        if detected_letter:
            if detected_letter == self.current_letter:
                if now - self.letter_start_time > self.confirm_duration:
                    # Letter confirmed!
                    self.current_word += self.current_letter
                    self.current_letter = None # Reset
                    self.last_action_time = now
                    return {"event": "letter_confirmed", "letter": detected_letter, "word": self.current_word, "full": self.translation}
            else:
                self.current_letter = detected_letter
                self.letter_start_time = now
        else:
            if self.current_word and now - self.last_action_time > 1.8:
                self.translation += " " + self.current_word
                self.translation = self.translation.strip()
                self.current_word = ""
                return {"event": "word_finished", "word": "", "full": self.translation}

        if now - self.last_action_time > 20.0:
             self.translation = ""

        return {"event": "idle", "letter": self.current_letter, "word": self.current_word, "full": self.translation}
