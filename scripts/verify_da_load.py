"""Verify Devil's Advocate code is loaded by querying the engine on miniPC."""
import os
import sys
sys.path.insert(0, r"C:\bitman_marketfloww")

from dotenv import load_dotenv
load_dotenv(r"C:\bitman_marketfloww\.env")

from engine.llm_analyzer import ClaudeDevilAdvocate, MultiAIConsensusScreener

print("DEVIL_ADVOCATE_ENABLED:", os.getenv("DEVIL_ADVOCATE_ENABLED"))
print("DEVIL_ADVOCATE_MODEL:", os.getenv("DEVIL_ADVOCATE_MODEL"))

s = MultiAIConsensusScreener()
print("MultiAI screeners:", list(s.screeners.keys()))
print("devil_advocate set:", s.devil_advocate is not None)
if s.devil_advocate:
    print("DA model:", s.devil_advocate.model_name)
    print("DA client:", s.devil_advocate.client is not None)

print("OK")
