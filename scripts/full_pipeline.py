"""Full pipeline: sequential KG extraction for all 7 textbooks, then integration + RAG index."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEXTBOOK_IDS = ["book_01", "book_02", "book_03", "book_04", "book_05", "book_06", "book_07"]
results = {}

def safe_print(msg):
    """Print safely with flush."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)

def extract_one(tid):
    """Extract knowledge graph for one textbook."""
    from backend.agents.kg_extraction_agent import extract_textbook_graph
    start = time.time()
    result = extract_textbook_graph(tid, force=True)
    elapsed = time.time() - start
    results[tid] = {"status": "OK", **result, "elapsed": round(elapsed, 1)}
    safe_print(f"  [OK] {tid}: {result.get('nodes', 0)} nodes, {result.get('edges', 0)} edges ({elapsed:.0f}s)")

def run_step(name, func):
    global_start = time.time()
    safe_print(f"\n{'='*60}")
    safe_print(f"STEP: {name}")
    safe_print(f"{'='*60}")
    result = func()
    safe_print(f"DONE in {time.time()-global_start:.0f}s")
    return result

def main():
    # ── Step 1: Sequential KG extraction ──
    def do_kg_extraction():
        for i, tid in enumerate(TEXTBOOK_IDS):
            safe_print(f"\n[{i+1}/7] Extracting knowledge graph for {tid} ...")
            try:
                extract_one(tid)
            except Exception as e:
                results[tid] = {"status": "FAIL", "error": str(e)}
                safe_print(f"  [FAIL] {tid}: {e}")

        total_nodes = sum(r.get("nodes", 0) for r in results.values())
        total_edges = sum(r.get("edges", 0) for r in results.values())
        ok = sum(1 for r in results.values() if r["status"] == "OK")
        safe_print(f"\nKG extraction: {ok}/{len(TEXTBOOK_IDS)} success, {total_nodes} nodes, {total_edges} edges")
        return results

    run_step("Knowledge Graph Extraction (7 textbooks - sequential)", do_kg_extraction)

    # ── Step 2: Cross-textbook alignment + compression ──
    run_step("Cross-textbook Alignment + Compression", align_and_compress)

    # ── Step 3: RAG Index ──
    run_step("RAG Index Building", build_rag)

    # ── Final summary ──
    safe_print(f"\n{'='*60}")
    safe_print("FULL PIPELINE COMPLETE")
    safe_print(f"{'='*60}")
    from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Chunk, Chapter
    db = SessionLocal()
    try:
        safe_print(f"  Textbooks: {db.query(Textbook).count()}")
        safe_print(f"  Chapters:  {db.query(Chapter).count()}")
        safe_print(f"  Chunks:    {db.query(Chunk).count()}")
        safe_print(f"  Nodes:     {db.query(KnowledgeNode).count()}")
        safe_print(f"  Edges:     {db.query(KnowledgeEdge).count()}")
        safe_print(f"  Decisions: {db.query(IntegrationDecision).count()}")
    finally:
        db.close()


def align_and_compress():
    from backend.agents.alignment_agent import align_all_textbooks
    from backend.agents.compression_agent import compress_knowledge
    safe_print("Aligning concepts across textbooks...")
    align_result = align_all_textbooks()
    safe_print(f"Alignment done: {align_result}")
    safe_print("Compressing knowledge to 30% target...")
    compress_result = compress_knowledge()
    safe_print(f"Compression done: {compress_result}")
    return {**align_result, **compress_result}

def build_rag():
    from backend.agents.rag_agent import build_rag_index
    result = build_rag_index()
    safe_print(f"RAG index: {result}")
    return result

if __name__ == "__main__":
    main()
