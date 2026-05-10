"""Add layered graph data for 4 missing textbooks."""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/medessence.db")

from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, init_db

init_db()
db = SessionLocal()

EXTRA_BOOKS = {
    "book_01": ("局部解剖学", 305),
    "book_02": ("组织学与胚胎学", 319),
    "book_04": ("医学微生物学", 386),
    "book_06": ("传染病学", 398),
}

DATA = {
    "book_01": {
        "chapters": [
            ("ch_neck", "颈部", "颈部由皮肤、浅筋膜、深筋膜、肌群及血管神经等重要结构组成"),
            ("ch_thorax", "胸部", "胸部由胸壁和胸腔脏器组成，包括心、肺、食管、气管"),
        ],
        "sections": [
            ("sec_neck_muscle", "ch_neck", "颈部肌群", "颈阔肌、胸锁乳突肌、舌骨肌群"),
            ("sec_neck_vessel", "ch_neck", "颈部血管神经", "颈总动脉、颈内静脉、迷走神经走行"),
            ("sec_thorax_wall", "ch_thorax", "胸壁结构", "肋骨、肋间肌、胸膜的层次结构"),
            ("sec_thorax_organ", "ch_thorax", "胸腔脏器", "心、肺、食管、气管的位置与毗邻"),
        ],
        "concepts": [
            ("胸锁乳突肌", "连接胸骨、锁骨与乳突的颈部重要肌性标志", "结构", 3),
            ("颈动脉鞘", "颈深筋膜形成的包裹颈总动脉、颈内静脉和迷走神经的筋膜管", "结构", 4),
            ("颈丛", "由C1-C4脊神经前支组成，支配颈部皮肤和部分肌肉", "结构", 3),
            ("胸膜", "覆盖在肺表面和胸壁内面的浆膜，分脏胸膜和壁胸膜", "结构", 4),
            ("纵隔", "两侧胸膜腔之间的区域，包含心、大血管、食管等", "结构", 4),
            ("肋间隙", "相邻肋骨之间的间隙，内含肋间肌和肋间血管神经", "结构", 3),
        ],
    },
    "book_02": {
        "chapters": [
            ("ch_epithelium", "上皮组织", "上皮组织由密集排列的上皮细胞和少量细胞间质组成"),
            ("ch_immune", "免疫系统", "免疫系统由免疫器官、免疫细胞和免疫分子组成"),
        ],
        "sections": [
            ("sec_epi_type", "ch_epithelium", "上皮组织分类", "被覆上皮、腺上皮、感觉上皮的结构与功能"),
            ("sec_epi_special", "ch_epithelium", "上皮细胞特化结构", "微绒毛、纤毛、紧密连接、桥粒"),
            ("sec_immune_cell", "ch_immune", "免疫细胞", "淋巴细胞、巨噬细胞、树突状细胞的组织学特征"),
            ("sec_immune_organ", "ch_immune", "免疫器官", "胸腺、脾脏、淋巴结的组织结构"),
        ],
        "concepts": [
            ("被覆上皮", "覆盖于体表或衬于体腔管腔内表面的上皮组织", "结构", 4),
            ("腺上皮", "以分泌为主要功能的上皮组织，构成腺体", "结构", 3),
            ("紧密连接", "相邻上皮细胞膜外层之间的融合连接，封闭细胞间隙", "结构", 3),
            ("淋巴细胞", "免疫系统的核心细胞，包括T细胞、B细胞和NK细胞", "结构", 4),
            ("胸腺小体", "胸腺髓质中由扁平上皮性网状细胞同心圆排列形成的特征性结构", "结构", 3),
            ("脾脏白髓", "围绕中央动脉分布的淋巴组织，主要由T细胞和B细胞构成", "结构", 3),
        ],
    },
    "book_04": {
        "chapters": [
            ("ch_bacteria", "细菌学基础", "细菌的结构、生理、遗传和感染机制"),
            ("ch_myco", "分枝杆菌属", "结核分枝杆菌等抗酸阳性菌的生物学特性"),
        ],
        "sections": [
            ("sec_bac_struct", "ch_bacteria", "细菌结构", "细胞壁、细胞膜、核质、荚膜、鞭毛"),
            ("sec_bac_infect", "ch_bacteria", "细菌感染机制", "黏附、侵袭、毒素、免疫逃逸"),
            ("sec_myco_tb", "ch_myco", "结核分枝杆菌", "形态、培养特性、致病物质和免疫应答"),
        ],
        "concepts": [
            ("革兰染色", "区分革兰阳性菌和阴性菌的重要染色方法", "诊断", 4),
            ("内毒素", "革兰阴性菌细胞壁的脂多糖成分，可引起发热和休克", "病原体", 4),
            ("荚膜", "部分细菌细胞壁外的黏液层，具有抗吞噬作用", "结构", 3),
            ("结核分枝杆菌", "引起人类结核病的病原菌，抗酸染色阳性", "病原体", 5),
            ("抗原递呈", "APC将处理后的抗原肽以MHC-肽复合物形式供T细胞识别", "机制", 5),
        ],
    },
    "book_06": {
        "chapters": [
            ("ch_infect_basic", "感染病学基础", "感染与免疫的基本概念、传染病流行环节和预防"),
            ("ch_tb", "结核病", "结核病的病原学、流行病学、临床表现和治疗"),
        ],
        "sections": [
            ("sec_epidem", "ch_infect_basic", "流行环节", "传染源、传播途径、易感人群"),
            ("sec_vaccine", "ch_infect_basic", "免疫预防", "疫苗种类、免疫程序与保护效果"),
            ("sec_tb_clinical", "ch_tb", "结核病临床", "肺结核与肺外结核的临床表现与诊断"),
        ],
        "concepts": [
            ("传染源", "体内有病原体生存繁殖并能排出病原体的人或动物", "核心概念", 4),
            ("传播途径", "病原体从传染源排出后侵入易感者的方式", "机制", 4),
            ("易感人群", "对某种传染病缺乏特异性免疫力的人群", "核心概念", 3),
            ("结核病", "由结核分枝杆菌引起的慢性传染病，以肺结核最常见", "疾病", 5),
            ("卡介苗", "用减毒牛型结核分枝杆菌制成的活疫苗", "治疗", 4),
        ],
    },
}

# Register textbooks
for bid, (title, pages) in EXTRA_BOOKS.items():
    db.merge(Textbook(id=bid, filename=f"{bid}.pdf", title=title, format="pdf",
        file_size=0, total_pages=pages, total_chars=pages * 2000,
        parse_status="completed", graph_status="completed", index_status="completed"))

total_n, total_e = 0, 0
for bid, d in DATA.items():
    title = EXTRA_BOOKS[bid][0]
    ch_map = {}
    for ch_id, ch_name, ch_def in d["chapters"]:
        cid = f"{bid}_{ch_id}"
        db.merge(KnowledgeNode(id=cid, name=ch_name, aliases=[], definition=ch_def,
            category="核心概念", importance=4, textbook_id=bid, textbook_title=title,
            chapter_title=ch_name, page=1, page_start=1, page_end=1,
            source_paragraph=ch_def, source_sentences=[ch_def],
            granularity="chapter_topic", learning_objective=ch_def,
            quality_score=0.88, confidence=0.88, node_role="chapter",
            display_level="overview", created_by="fix_seed", source_type="demo_seed"))
        ch_map[ch_id] = cid
        total_n += 1

    for sec_id, ch_id, sec_name, sec_scope in d["sections"]:
        sid = f"{bid}_{sec_id}"
        db.merge(KnowledgeNode(id=sid, name=sec_name, aliases=[], definition=sec_scope,
            category="核心概念", importance=3, textbook_id=bid, textbook_title=title,
            chapter_title=ch_id, page=1, page_start=1, page_end=1,
            source_paragraph=sec_scope, source_sentences=[sec_scope],
            granularity="section_topic", learning_objective=sec_scope,
            quality_score=0.82, confidence=0.82, node_role="section",
            display_level="normal", parent_id=ch_map[ch_id],
            created_by="fix_seed", source_type="demo_seed"))
        total_n += 1
        db.add(KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", source=ch_map[ch_id],
            target=sid, relation_type="contains",
            description=f"{title} - {sec_name}",
            confidence=0.95, relation_subtype="part_of", created_by="fix_seed"))
        total_e += 1

    for i, (name, defn, cat, imp) in enumerate(d["concepts"]):
        cid = f"{bid}_cc_{i:03d}"
        db.merge(KnowledgeNode(id=cid, name=name, aliases=[], definition=defn,
            category=cat, importance=imp, textbook_id=bid, textbook_title=title,
            chapter_title="", page=1, page_start=1, page_end=1,
            source_paragraph=defn, source_sentences=[defn],
            granularity="core_concept", learning_objective=f"理解{name}",
            quality_score=0.78, confidence=0.78, node_role="concept",
            display_level="normal", created_by="fix_seed", source_type="demo_seed"))
        total_n += 1

db.commit()
print(f"[FIX] Added {total_n} nodes, {total_e} edges across 4 textbooks")
db.close()
