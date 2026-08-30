"""Continue pipeline from alignment step (KG extraction already done)."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def safe_print(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)

safe_print("="*60)
safe_print("CONTINUING FROM ALIGNMENT STEP")
safe_print("="*60)

# Step 1: Alignment
safe_print("\n[1/3] Cross-textbook Alignment...")
t0 = time.time()
from backend.agents.alignment_agent import align_all_textbooks
align_result = align_all_textbooks()
safe_print(f"Alignment done in {time.time()-t0:.0f}s: {align_result}")

# Step 2: Compression
safe_print("\n[2/3] Knowledge Compression...")
t0 = time.time()
from backend.agents.compression_agent import compress_knowledge
compress_result = compress_knowledge()
safe_print(f"Compression done in {time.time()-t0:.0f}s: {compress_result}")

# Step 3: RAG Index
safe_print("\n[3/3] Building RAG Index...")
t0 = time.time()
from backend.agents.rag_agent import build_rag_index
rag_result = build_rag_index()
safe_print(f"RAG index done in {time.time()-t0:.0f}s: {rag_result}")

# Summary
safe_print(f"\n{'='*60}")
safe_print("PIPELINE COMPLETE")
safe_print(f"{'='*60}")
from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Chunk, Chapter
db = SessionLocal()
try:
    safe_print(f"  Textbooks:  {db.query(Textbook).count()}")
    safe_print(f"  Chapters:   {db.query(Chapter).count()}")
    safe_print(f"  Chunks:     {db.query(Chunk).count()}")
    safe_print(f"  Nodes:      {db.query(KnowledgeNode).count()}")
    safe_print(f"  Edges:      {db.query(KnowledgeEdge).count()}")
    safe_print(f"  Decisions:  {db.query(IntegrationDecision).count()}")
finally:
    db.close()
