import time
import uuid
from fastapi import APIRouter, BackgroundTasks
from backend.config import LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
from backend.agents.rag_agent import query_rag
from backend.database import SessionLocal

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

BENCHMARK_QUESTIONS = [
    {"question": "炎症的定义是什么？", "type": "事实型", "expected_textbook": "病理学", "expected_chapter": "第四章 炎症"},
    {"question": "动作电位和静息电位有什么关系？", "type": "比较型", "expected_textbook": "生理学", "expected_chapter": "第二章 细胞的基本功能"},
    {"question": "结核分枝杆菌的致病特点是什么？", "type": "事实型", "expected_textbook": "医学微生物学", "expected_chapter": "第十六章 分枝杆菌属"},
    {"question": "炎症的基本病理变化包括哪些？", "type": "事实型", "expected_textbook": "病理学", "expected_chapter": "第四章 炎症"},
    {"question": "免疫应答的主要过程是什么？", "type": "事实型", "expected_textbook": "医学微生物学", "expected_chapter": "第八章 免疫应答"},
    {"question": "休克的定义和发生机制是什么？", "type": "推理型", "expected_textbook": "病理生理学", "expected_chapter": "第五章 休克"},
    {"question": "结核病是如何传播的？", "type": "事实型", "expected_textbook": "传染病学", "expected_chapter": "第十章 结核病"},
    {"question": "上皮组织的主要特点是什么？", "type": "事实型", "expected_textbook": "组织学与胚胎学", "expected_chapter": "第三章 上皮组织"},
    {"question": "发热的病理生理机制是什么？", "type": "推理型", "expected_textbook": "病理生理学", "expected_chapter": "第二章 发热"},
    {"question": "抗原递呈在免疫应答中起什么作用？", "type": "推理型", "expected_textbook": "医学微生物学", "expected_chapter": "第八章 免疫应答"},
    {"question": "细胞损伤的机制有哪些？", "type": "事实型", "expected_textbook": "病理学", "expected_chapter": "第一章 细胞损伤"},
    {"question": "结核分枝杆菌的病原学特点如何影响结核病的临床表现？", "type": "跨教材型", "expected_textbook": "医学微生物学/传染病学", "expected_chapter": ""},
    {"question": "颈部有哪些重要的解剖结构？", "type": "事实型", "expected_textbook": "局部解剖学", "expected_chapter": "第三章 颈部"},
    {"question": "炎症在生理学和病理学中的描述有何异同？", "type": "跨教材型", "expected_textbook": "病理学/生理学", "expected_chapter": ""},
    {"question": "胸部的血液供应有什么特点？", "type": "事实型", "expected_textbook": "局部解剖学", "expected_chapter": "第五章 胸部"},
    {"question": "细菌如何引起机体感染？", "type": "推理型", "expected_textbook": "医学微生物学", "expected_chapter": ""},
    {"question": "变质、渗出和增生三者之间有什么关系？", "type": "比较型", "expected_textbook": "病理学", "expected_chapter": "第四章 炎症"},
    {"question": "免疫细胞的组织学特征是什么？", "type": "跨教材型", "expected_textbook": "组织学与胚胎学", "expected_chapter": "第七章 免疫系统"},
    {"question": "血液循环的生理学基础是什么？", "type": "事实型", "expected_textbook": "生理学", "expected_chapter": "第四章 血液循环"},
    {"question": "一种不存在的医学概念X的临床表现有哪些？", "type": "拒答型", "expected_textbook": "", "expected_chapter": ""},
]

_result_cache = []

@router.get("")
def get_benchmark():
    # Return array when empty, object with results when populated
    if not _result_cache:
        return []
    return _result_cache

@router.post("/run")
def run_benchmark(bg: BackgroundTasks):
    bg.add_task(_run_benchmark_task)
    return {"status": "started", "questions": len(BENCHMARK_QUESTIONS)}

def _run_benchmark_task():
    global _result_cache
    results = []
    for q in BENCHMARK_QUESTIONS:
        start = time.time()
        try:
            result = query_rag(q["question"])
            latency = time.time() - start
            has_citations = len(result.get("citations", [])) > 0
            citation_hit = False
            if has_citations and q["expected_textbook"]:
                expected_parts = q["expected_textbook"].split("/")
                for cit in result.get("citations", []):
                    if cit.get("textbook", "") in expected_parts:
                        citation_hit = True
                        break
            no_answer_correct = "未找到" in result.get("answer", "") if q["type"] == "拒答型" else None
            results.append({
                "id": str(uuid.uuid4().hex[:8]),
                "question": q["question"],
                "type": q["type"],
                "answer_preview": result.get("answer", "")[:200],
                "citations_count": len(result.get("citations", [])),
                "citation_hit": citation_hit,
                "no_answer_correct": no_answer_correct,
                "latency_s": round(latency, 3),
            })
        except Exception as e:
            results.append({
                "id": str(uuid.uuid4().hex[:8]),
                "question": q["question"],
                "type": q["type"],
                "answer_preview": f"ERROR: {str(e)[:200]}",
                "citations_count": 0,
                "citation_hit": False,
                "no_answer_correct": None,
                "latency_s": round(time.time() - start, 3),
            })

    # Summary stats
    total = len(results)
    hits = sum(1 for r in results if r["citation_hit"])
    avg_latency = sum(r["latency_s"] for r in results) / max(total, 1)
    no_answer_ok = sum(1 for r in results if r["no_answer_correct"] is True)

    _result_cache = results
    # Write summary as first entry
    _result_cache.insert(0, {
        "id": "summary",
        "question": "BENCHMARK SUMMARY",
        "type": "summary",
        "answer_preview": f"Citation命中率: {hits}/{total-hits} | 平均延迟: {avg_latency:.2f}s | 拒答正确: {no_answer_ok}",
        "citations_count": hits,
        "citation_hit": True,
        "no_answer_correct": None,
        "latency_s": avg_latency,
    })
