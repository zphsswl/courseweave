"""Setup script: register textbooks and create demo knowledge graph data."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(__file__))

from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Chapter, Chunk, init_db

init_db()

PDFS = [
    ("book_01", "01_局部解剖学.pdf", "局部解剖学", 305),
    ("book_02", "02_组织学与胚胎学.pdf", "组织学与胚胎学", 319),
    ("book_03", "03_生理学.pdf", "生理学", 450),
    ("book_04", "04_医学微生物学.pdf", "医学微生物学", 386),
    ("book_05", "05_病理学.pdf", "病理学", 418),
    ("book_06", "06_传染病学.pdf", "传染病学", 398),
    ("book_07", "07_病理生理学.pdf", "病理生理学", 291),
]

DEMO_NODES = [
    # 病理学 nodes
    {"id": "book_05_node_001", "name": "炎症", "aliases": ["炎症反应", "inflammation"], "definition": "具有血管系统的活体组织对损伤因子发生的防御性反应。", "category": "核心概念", "importance": 5, "textbook_id": "book_05", "textbook_title": "病理学", "chapter_title": "第四章 炎症", "page": 78, "source_paragraph": "炎症是具有血管系统的活体组织对各种损伤因子的刺激所发生的防御性反应，其基本病理变化包括变质、渗出和增生。"},
    {"id": "book_05_node_002", "name": "变质", "aliases": ["alteration"], "definition": "炎症局部组织发生的变性和坏死。", "category": "机制", "importance": 4, "textbook_id": "book_05", "textbook_title": "病理学", "chapter_title": "第四章 炎症", "page": 80, "source_paragraph": "变质是指炎症局部组织发生的变性和坏死，是炎症最早期的变化。"},
    {"id": "book_05_node_003", "name": "渗出", "aliases": ["exudation"], "definition": "炎症局部组织血管内的液体和细胞成分通过血管壁进入组织间隙的过程。", "category": "机制", "importance": 4, "textbook_id": "book_05", "textbook_title": "病理学", "chapter_title": "第四章 炎症", "page": 82, "source_paragraph": "渗出是炎症最具特征性的变化，包括血管反应、液体渗出和白细胞渗出。"},
    {"id": "book_05_node_004", "name": "增生", "aliases": ["proliferation"], "definition": "炎症局部组织的再生与增殖，以修复损伤组织。", "category": "机制", "importance": 3, "textbook_id": "book_05", "textbook_title": "病理学", "chapter_title": "第四章 炎症", "page": 85, "source_paragraph": "增生是炎症后期以修复为主的变化，包括实质细胞和间质细胞的增生。"},
    {"id": "book_05_node_005", "name": "细胞损伤", "aliases": ["cell injury"], "definition": "细胞在内外环境变化下发生的形态和功能改变。", "category": "核心概念", "importance": 5, "textbook_id": "book_05", "textbook_title": "病理学", "chapter_title": "第一章 细胞损伤", "page": 12, "source_paragraph": "细胞损伤是疾病发生的基础，包括可逆性损伤和不可逆性损伤。"},
    # 生理学 nodes
    {"id": "book_03_node_001", "name": "动作电位", "aliases": ["action potential", "AP"], "definition": "可兴奋细胞受刺激时产生的快速、可逆的膜电位变化。", "category": "核心概念", "importance": 5, "textbook_id": "book_03", "textbook_title": "生理学", "chapter_title": "第二章 细胞的基本功能", "page": 28, "source_paragraph": "动作电位是可兴奋细胞在静息电位基础上受到适当刺激时产生的快速而可逆的电位变化。"},
    {"id": "book_03_node_002", "name": "静息电位", "aliases": ["resting potential"], "definition": "细胞在安静状态下膜两侧存在的内负外正电位差。", "category": "核心概念", "importance": 5, "textbook_id": "book_03", "textbook_title": "生理学", "chapter_title": "第二章 细胞的基本功能", "page": 24, "source_paragraph": "静息电位是指细胞在安静状态下存在于细胞膜两侧的电位差，表现为膜内为负、膜外为正。"},
    {"id": "book_03_node_003", "name": "血液循环", "aliases": ["blood circulation"], "definition": "血液在心血管系统中周而复始的流动过程。", "category": "核心概念", "importance": 4, "textbook_id": "book_03", "textbook_title": "生理学", "chapter_title": "第四章 血液循环", "page": 56, "source_paragraph": "血液循环是指血液在心血管系统中按一定方向周而复始地流动。"},
    {"id": "book_03_node_004", "name": "炎症反应", "aliases": ["炎症", "inflammatory response"], "definition": "机体对损伤因子的防御性反应，涉及血管、免疫和体液调节。", "category": "核心概念", "importance": 4, "textbook_id": "book_03", "textbook_title": "生理学", "chapter_title": "第八章 免疫与防御", "page": 198, "source_paragraph": "炎症反应是机体对损伤因子的综合性防御反应，包括局部血管扩张、通透性增加和白细胞游出等过程。"},
    # 病理生理学 nodes
    {"id": "book_07_node_001", "name": "炎症", "aliases": ["炎症反应", "inflammation"], "definition": "具有血管系统的活体组织对各种致炎因素引起的损伤所发生的以防御为主的反应。", "category": "核心概念", "importance": 5, "textbook_id": "book_07", "textbook_title": "病理生理学", "chapter_title": "第三章 炎症", "page": 45, "source_paragraph": "炎症是具有血管系统的活体组织对各种致炎因素引起的损伤所发生的以防御为主的综合性病理过程。"},
    {"id": "book_07_node_002", "name": "发热", "aliases": ["fever"], "definition": "致热原作用下体温调节中枢调定点上移引起的体温升高。", "category": "核心概念", "importance": 4, "textbook_id": "book_07", "textbook_title": "病理生理学", "chapter_title": "第二章 发热", "page": 22, "source_paragraph": "发热是指在致热原作用下，体温调节中枢的调定点上移而引起的体温升高。"},
    {"id": "book_07_node_003", "name": "休克", "aliases": ["shock"], "definition": "各种强烈致病因子作用于机体引起的急性循环衰竭。", "category": "核心概念", "importance": 5, "textbook_id": "book_07", "textbook_title": "病理生理学", "chapter_title": "第五章 休克", "page": 78, "source_paragraph": "休克是各种强烈致病因子作用于机体引起的急性循环衰竭，其特点是组织微循环灌流严重不足。"},
    # 医学微生物学 nodes
    {"id": "book_04_node_001", "name": "结核分枝杆菌", "aliases": ["Mycobacterium tuberculosis", "结核杆菌"], "definition": "引起结核病的病原菌，抗酸染色阳性。", "category": "病原体", "importance": 5, "textbook_id": "book_04", "textbook_title": "医学微生物学", "chapter_title": "第十六章 分枝杆菌属", "page": 234, "source_paragraph": "结核分枝杆菌是引起人类结核病的病原菌，为细长略带弯曲的杆菌，抗酸染色阳性。"},
    {"id": "book_04_node_002", "name": "抗原递呈", "aliases": ["antigen presentation"], "definition": "抗原递呈细胞将抗原肽-MHC复合物表达于细胞表面供T细胞识别的过程。", "category": "机制", "importance": 4, "textbook_id": "book_04", "textbook_title": "医学微生物学", "chapter_title": "第八章 免疫应答", "page": 112, "source_paragraph": "抗原递呈是指APC将处理后的抗原肽以MHC-肽复合物形式表达于细胞表面，供T细胞识别。"},
    {"id": "book_04_node_003", "name": "免疫应答", "aliases": ["immune response"], "definition": "机体免疫系统识别和清除抗原的全过程。", "category": "核心概念", "importance": 5, "textbook_id": "book_04", "textbook_title": "医学微生物学", "chapter_title": "第八章 免疫应答", "page": 108, "source_paragraph": "免疫应答是机体免疫系统识别和清除抗原性异物的全过程，包括固有免疫和适应性免疫。"},
    # 传染病学 nodes
    {"id": "book_06_node_001", "name": "结核病", "aliases": ["tuberculosis", "TB"], "definition": "由结核分枝杆菌引起的慢性传染病，以肺结核最常见。", "category": "疾病", "importance": 5, "textbook_id": "book_06", "textbook_title": "传染病学", "chapter_title": "第十章 结核病", "page": 156, "source_paragraph": "结核病是由结核分枝杆菌引起的慢性传染病，可累及全身多个器官，以肺结核最为常见。"},
    {"id": "book_06_node_002", "name": "传播途径", "aliases": ["transmission route"], "definition": "病原体从传染源排出后侵入易感者的方式。", "category": "机制", "importance": 3, "textbook_id": "book_06", "textbook_title": "传染病学", "chapter_title": "第一章 总论", "page": 8, "source_paragraph": "传播途径是指病原体从传染源排出后，侵入新的易感宿主之前在外环境中经历的全部过程。"},
    {"id": "book_06_node_003", "name": "免疫应答", "aliases": ["immune response"], "definition": "机体对抗原性异物的识别与清除反应。", "category": "核心概念", "importance": 4, "textbook_id": "book_06", "textbook_title": "传染病学", "chapter_title": "第二章 感染与免疫", "page": 22, "source_paragraph": "免疫应答是机体识别和排除抗原性异物、维持自身生理平衡的保护性反应。"},
    # 组织学与胚胎学 nodes
    {"id": "book_02_node_001", "name": "上皮组织", "aliases": ["epithelial tissue"], "definition": "由密集排列的上皮细胞和少量细胞间质组成的基本组织。", "category": "结构", "importance": 4, "textbook_id": "book_02", "textbook_title": "组织学与胚胎学", "chapter_title": "第三章 上皮组织", "page": 42, "source_paragraph": "上皮组织由大量形态规则、排列密集的细胞和极少量的细胞间质组成。"},
    {"id": "book_02_node_002", "name": "免疫细胞", "aliases": ["immune cells"], "definition": "参与免疫应答的细胞统称，包括淋巴细胞、巨噬细胞等。", "category": "结构", "importance": 3, "textbook_id": "book_02", "textbook_title": "组织学与胚胎学", "chapter_title": "第七章 免疫系统", "page": 128, "source_paragraph": "免疫细胞是参与机体免疫应答的细胞，主要包括淋巴细胞、单核巨噬细胞、树突状细胞等。"},
    # 局部解剖学 nodes
    {"id": "book_01_node_001", "name": "颈部解剖", "aliases": ["cervical anatomy"], "definition": "颈部由皮肤、浅筋膜、深筋膜、肌群、血管神经等构成。", "category": "结构", "importance": 3, "textbook_id": "book_01", "textbook_title": "局部解剖学", "chapter_title": "第三章 颈部", "page": 92, "source_paragraph": "颈部位于头部与胸部之间，由皮肤、浅筋膜、深筋膜、肌群及血管神经等重要结构组成。"},
    {"id": "book_01_node_002", "name": "胸腔脏器", "aliases": ["thoracic organs"], "definition": "胸腔内包含心、肺、食管、气管等重要器官及其血管神经。", "category": "结构", "importance": 3, "textbook_id": "book_01", "textbook_title": "局部解剖学", "chapter_title": "第五章 胸部", "page": 156, "source_paragraph": "胸腔内主要脏器包括心、肺、食管和气管等，各器官借纵隔结构相互分隔和联系。"},
]

DEMO_EDGES = [
    {"source": "book_05_node_001", "target": "book_05_node_002", "relation_type": "contains", "description": "炎症包含变质过程"},
    {"source": "book_05_node_001", "target": "book_05_node_003", "relation_type": "contains", "description": "炎症包含渗出过程"},
    {"source": "book_05_node_001", "target": "book_05_node_004", "relation_type": "contains", "description": "炎症包含增生过程"},
    {"source": "book_03_node_002", "target": "book_03_node_001", "relation_type": "prerequisite", "description": "静息电位是理解动作电位的基础"},
    {"source": "book_03_node_003", "target": "book_03_node_001", "relation_type": "applies_to", "description": "动作电位是血液循环中传导的基础"},
    {"source": "book_04_node_003", "target": "book_04_node_002", "relation_type": "contains", "description": "免疫应答包含抗原递呈过程"},
    {"source": "book_04_node_001", "target": "book_06_node_001", "relation_type": "applies_to", "description": "结核分枝杆菌是结核病的病原体"},
    {"source": "book_05_node_005", "target": "book_05_node_001", "relation_type": "prerequisite", "description": "细胞损伤可引发炎症反应"},
    {"source": "book_02_node_001", "target": "book_05_node_001", "relation_type": "applies_to", "description": "上皮组织屏障破坏可导致炎症"},
    {"source": "book_07_node_001", "target": "book_05_node_001", "relation_type": "parallel", "description": "病理学与病理生理学均讲解炎症"},
]

DEMO_DECISIONS = [
    {"id": "dec_001", "action": "merge", "affected_nodes": ["book_05_node_001", "book_07_node_001", "book_03_node_004"], "result_node": "merged_inflammation", "result_name": "炎症", "reason": "病理学、病理生理学和生理学均涉及炎症，病理学定义最系统，已合并为统一概念。", "confidence": 0.92},
    {"id": "dec_002", "action": "keep", "affected_nodes": ["book_04_node_003"], "result_node": "", "result_name": "免疫应答", "reason": "免疫应答为关键核心概念，在微生物学和传染病学中互补，保留为独立节点。", "confidence": 0.88},
    {"id": "dec_003", "action": "keep", "affected_nodes": ["book_04_node_001", "book_06_node_001"], "result_node": "", "result_name": "结核分枝杆菌/结核病", "reason": "微生物学和传染病学形成互补：微生物学讲病原体，传染病学讲传播和临床表现。", "confidence": 0.95},
    {"id": "dec_004", "action": "keep", "affected_nodes": ["book_03_node_001", "book_03_node_002"], "result_node": "", "result_name": "动作电位/静息电位", "reason": "两者为紧密相关的前置依赖概念，需同时保留以保证教学连贯性。", "confidence": 0.90},
    {"id": "dec_005", "action": "remove", "affected_nodes": ["book_01_node_001"], "result_node": "", "result_name": "颈部解剖", "reason": "解剖结构信息丰富但与核心病理生理概念关联度较低，纳入但降低权重。", "confidence": 0.55},
]

DEMO_CHUNKS = [
    {"id": "chunk_001", "textbook_id": "book_05", "chapter_id": "ch_demo_001", "textbook_title": "病理学", "chapter_title": "第四章 炎症", "content": "炎症是具有血管系统的活体组织对各种损伤因子的刺激所发生的防御性反应，其基本病理变化包括变质、渗出和增生。变质是指炎症局部组织发生的变性和坏死。渗出是炎症最具特征性的变化，包括血管反应、液体渗出和白细胞渗出。增生是炎症后期以修复为主的变化。", "page_start": 78, "char_count": 150},
    {"id": "chunk_002", "textbook_id": "book_03", "chapter_id": "ch_demo_002", "textbook_title": "生理学", "chapter_title": "第八章 免疫与防御", "content": "炎症反应是机体对损伤因子的综合性防御反应，包括局部血管扩张、通透性增加和白细胞游出等过程。炎症反应的程度和持续时间取决于损伤因子的性质和机体的反应状态。", "page_start": 198, "char_count": 100},
    {"id": "chunk_003", "textbook_id": "book_07", "chapter_id": "ch_demo_003", "textbook_title": "病理生理学", "chapter_title": "第三章 炎症", "content": "炎症是具有血管系统的活体组织对各种致炎因素引起的损伤所发生的以防御为主的综合性病理过程。炎症的发生发展涉及多种炎症介质的参与，包括血管活性胺类、激肽系统、补体系统等。", "page_start": 45, "char_count": 120},
]

db = SessionLocal()
try:
    # Register textbooks
    for bid, fname, title, pages in PDFS:
        book = Textbook(
            id=bid, filename=fname, title=title, format="pdf",
            file_size=0, total_pages=pages, total_chars=pages * 2000,
            parse_status="completed", graph_status="completed", index_status="completed"
        )
        db.merge(book)

    # Create demo nodes
    for n in DEMO_NODES:
        node = KnowledgeNode(
            id=n["id"], name=n["name"], aliases=n.get("aliases", []),
            definition=n.get("definition", ""), category=n.get("category", ""),
            importance=n.get("importance", 3), textbook_id=n["textbook_id"],
            textbook_title=n["textbook_title"], chapter_title=n.get("chapter_title", ""),
            page=n.get("page", 1), source_paragraph=n.get("source_paragraph", ""),
            source_sentences=[n.get("source_paragraph", "")],
            is_merged=False, teacher_locked=False
        )
        db.merge(node)

    # Create demo edges
    for e in DEMO_EDGES:
        edge = KnowledgeEdge(
            id=f"edge_{uuid.uuid4().hex[:8]}",
            source=e["source"], target=e["target"],
            relation_type=e["relation_type"], description=e.get("description", ""),
            confidence=0.85
        )
        db.add(edge)

    # Create demo chunks
    for c in DEMO_CHUNKS:
        chunk = Chunk(
            id=c["id"], textbook_id=c["textbook_id"], chapter_id=c["chapter_id"],
            textbook_title=c["textbook_title"], chapter_title=c["chapter_title"],
            page_start=c["page_start"], page_end=c["page_start"] + 1,
            content=c["content"], char_count=c["char_count"], chunk_index=0
        )
        db.merge(chunk)

    # Create demo decisions
    for d in DEMO_DECISIONS:
        dec = IntegrationDecision(
            id=d["id"], action=d["action"], affected_nodes=d["affected_nodes"],
            result_node=d.get("result_node", ""), result_name=d["result_name"],
            reason=d["reason"], confidence=d["confidence"], teacher_override=False
        )
        db.merge(dec)

    db.commit()
    print(f"[OK] Registered {len(PDFS)} textbooks")
    print(f"[OK] Created {len(DEMO_NODES)} knowledge nodes")
    print(f"[OK] Created {len(DEMO_EDGES)} knowledge edges")
    print(f"[OK] Created {len(DEMO_CHUNKS)} RAG chunks")
    print(f"[OK] Created {len(DEMO_DECISIONS)} integration decisions")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
    raise
finally:
    db.close()
