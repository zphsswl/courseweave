"""
Create layered demo data: chapter_topics → section_topics → core_concepts.
Moderate node count: 25-50 core nodes per book.
Demonstrates the layered knowledge graph structure.
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/medessence.db")

from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, init_db

init_db()
db = SessionLocal()

def mkid(prefix, *parts):
    return f"{prefix}_" + "_".join(str(p) for p in parts)

SEED = "layered_demo"

# ── Layer 1: Textbook registration ──
BOOKS = {
    "book_05": ("病理学", 418),
    "book_03": ("生理学", 450),
    "book_07": ("病理生理学", 291),
}

for bid, (title, pages) in BOOKS.items():
    db.merge(Textbook(id=bid, filename=f"{bid}.pdf", title=title, format="pdf",
        file_size=0, total_pages=pages, total_chars=pages*2000,
        parse_status="completed", graph_status="completed", index_status="completed"))

# ── Layer 2: Chapter topics ──
CHAPTER_TOPICS = {
    "book_05": [
        ("ch_inflame", "炎症", "本章围绕炎症的定义、病因、基本病理变化和结局展开。", "掌握炎症的概念、基本病理变化及其临床意义"),
        ("ch_injury", "细胞损伤与修复", "本章讲解细胞损伤的原因、机制、类型及修复过程。", "理解细胞损伤的可逆与不可逆变化及其临床后果"),
        ("ch_tumor", "肿瘤", "本章介绍肿瘤的概念、分类、病因、病理特征和临床意义。", "掌握肿瘤的基本概念、良恶性鉴别和病理特征"),
    ],
    "book_03": [
        ("ch_cell", "细胞的基本功能", "本章讲解细胞膜的物质转运、信号转导和电活动。", "掌握静息电位、动作电位的产生机制和细胞信号传递"),
        ("ch_circ", "血液循环", "本章介绍心脏泵血、血管功能和心血管调节。", "理解心脏泵血机制、血压调节和微循环"),
    ],
    "book_07": [
        ("ch_inflame_pp", "炎症的病理生理", "本章从病理生理角度阐述炎症的发生机制和调控。", "掌握炎症介质、炎症的全身反应和多器官影响"),
        ("ch_fever", "发热", "本章讲解发热的机制、分期和机体代谢变化。", "理解致热原、体温调定点上移和发热的临床意义"),
    ],
}

# ── Layer 3: Section topics ──
SECTION_TOPICS = {
    # 病理学 - 炎症 chapter
    ("book_05", "ch_inflame"): [
        ("sec_inflame_def", "炎症的定义与特征", "炎症的概念、基本特征和临床分类"),
        ("sec_inflame_alter", "变质", "炎症局部组织的变性与坏死"),
        ("sec_inflame_exudate", "渗出", "血管反应、液体渗出和白细胞游出"),
        ("sec_inflame_prolif", "增生", "炎症后期组织修复与再生"),
        ("sec_inflame_mediator", "炎症介质", "参与炎症反应的主要化学介质及其作用"),
    ],
    # 病理学 - 细胞损伤 chapter
    ("book_05", "ch_injury"): [
        ("sec_injury_cause", "细胞损伤的原因", "物理、化学、生物、缺氧等致伤因素"),
        ("sec_injury_mech", "细胞损伤的机制", "ATP耗竭、氧化应激、钙超载等机制"),
        ("sec_injury_type", "可逆与不可逆损伤", "变性、坏死、凋亡的形态学特征"),
        ("sec_repair", "组织修复", "再生与纤维性修复的机制"),
    ],
    # 生理学 - 细胞功能 chapter
    ("book_03", "ch_cell"): [
        ("sec_rest_pot", "静息电位", "细胞膜电位基础、离子分布和平衡电位"),
        ("sec_action_pot", "动作电位", "去极化、复极化和不应期"),
        ("sec_signal", "细胞信号转导", "受体、G蛋白和第二信使系统"),
    ],
    # 生理学 - 血液循环 chapter
    ("book_03", "ch_circ"): [
        ("sec_heart", "心脏泵血功能", "心动周期、心输出量和心泵调节"),
        ("sec_vessel", "血管生理", "血流动力学、血压和微循环"),
        ("sec_reg", "心血管调节", "神经调节、体液调节和自身调节"),
    ],
    # 病理生理学 - 炎症 chapter
    ("book_07", "ch_inflame_pp"): [
        ("sec_inflame_pp_def", "炎症的病理生理概述", "炎症作为基本病理过程的定位和全身影响"),
        ("sec_inflame_pp_mediator", "炎症介质与信号通路", "参与炎症的主要细胞因子、趋化因子和信号通路"),
        ("sec_inflame_pp_sys", "炎症的全身反应", "急性期反应、SIRS和抗炎反应"),
    ],
    # 病理生理学 - 发热 chapter
    ("book_07", "ch_fever"): [
        ("sec_fever_mech", "发热的发生机制", "外源性/内源性致热原、体温调定点"),
        ("sec_fever_phase", "发热的分期", "体温上升期、高热持续期和退热期"),
        ("sec_fever_meta", "发热的代谢变化", "发热时物质代谢和器官功能改变"),
    ],
}

# ── Layer 4: Core concepts ──
CORE_CONCEPTS = {
    ("book_05", "sec_inflame_def"): [
        ("炎症", ["炎症反应", "inflammation"], "具有血管系统的活体组织对损伤因子发生的防御性反应", "核心概念", 5),
        ("变质", ["alteration"], "炎症局部组织发生的变性和坏死", "机制", 4),
        ("渗出", ["exudation"], "炎症局部血管内液体和细胞成分通过血管壁进入组织间隙", "机制", 5),
        ("增生", ["proliferation"], "炎症后期以修复为主的细胞增殖过程", "机制", 4),
        ("趋化作用", ["chemotaxis"], "白细胞沿化学浓度梯度向炎症灶定向移动", "机制", 3),
    ],
    ("book_05", "sec_inflame_exudate"): [
        ("血管反应", ["vascular response"], "炎症时微血管扩张、血流加速、通透性增高", "机制", 4),
        ("白细胞游出", ["leukocyte emigration"], "白细胞通过血管壁进入组织的过程", "机制", 4),
        ("血管通透性增高", ["vascular permeability"], "炎症介质引起内皮细胞收缩、血管通透性增加", "机制", 3),
        ("液体渗出", ["fluid exudation"], "富含蛋白质的液体进入组织间隙形成炎性水肿", "机制", 4),
        ("吞噬作用", ["phagocytosis"], "巨噬细胞和中性粒细胞吞噬病原体和坏死碎片", "机制", 4),
    ],
    ("book_05", "sec_inflame_mediator"): [
        ("组胺", ["histamine"], "肥大细胞释放的重要炎症介质，引起血管扩张和通透性增加", "机制", 3),
        ("补体系统", ["complement system"], "血浆蛋白级联激活参与炎症和免疫防御", "机制", 4),
        ("细胞因子", ["cytokines"], "IL-1、TNF、IL-6等介导炎症反应和全身效应", "机制", 4),
        ("前列腺素", ["prostaglandin"], "花生四烯酸代谢产物，参与发热、疼痛和血管反应", "机制", 3),
    ],
    ("book_05", "sec_injury_mech"): [
        ("ATP耗竭", ["ATP depletion"], "缺氧或线粒体损伤导致细胞能量供应不足", "机制", 4),
        ("氧化应激", ["oxidative stress"], "自由基过量产生导致脂质过氧化和蛋白损伤", "机制", 4),
        ("钙超载", ["calcium overload"], "细胞内Ca2+浓度异常升高激活多种降解酶", "机制", 3),
        ("膜损伤", ["membrane damage"], "细胞膜完整性丧失导致细胞内容物外泄", "机制", 3),
    ],
    ("book_05", "sec_injury_type"): [
        ("坏死", ["necrosis"], "细胞不可逆损伤后发生的被动性死亡，伴随炎症反应", "机制", 4),
        ("凋亡", ["apoptosis"], "基因调控的程序性细胞死亡，不引起炎症", "机制", 4),
        ("变性", ["degeneration"], "细胞代谢障碍导致的可逆性形态学改变", "机制", 3),
    ],
    ("book_03", "sec_rest_pot"): [
        ("静息电位", ["resting potential", "RP"], "细胞在安静状态下膜两侧的内负外正电位差", "核心概念", 5),
        ("钠钾泵", ["Na+/K+ ATPase"], "主动转运Na+和K+维持细胞内外离子浓度梯度", "机制", 4),
        ("离子通道", ["ion channel"], "细胞膜上允许特定离子顺浓度梯度通过的蛋白质孔道", "结构", 4),
        ("平衡电位", ["equilibrium potential"], "某种离子在膜两侧的电化学平衡电位", "核心概念", 3),
    ],
    ("book_03", "sec_action_pot"): [
        ("动作电位", ["action potential", "AP"], "可兴奋细胞受刺激时产生的快速可逆膜电位变化", "核心概念", 5),
        ("去极化", ["depolarization"], "膜电位向正值方向变化的过程，主要由Na+内流引起", "机制", 4),
        ("复极化", ["repolarization"], "膜电位恢复到静息水平的过程，主要由K+外流引起", "机制", 4),
        ("不应期", ["refractory period"], "动作电位后细胞暂时丧失兴奋性的时期", "机制", 3),
        ("阈电位", ["threshold potential"], "触发动作电位所需的最小去极化电位", "核心概念", 3),
    ],
    ("book_03", "sec_heart"): [
        ("心动周期", ["cardiac cycle"], "心脏一次收缩和舒张的完整过程", "核心概念", 4),
        ("心输出量", ["cardiac output"], "每分钟一侧心室泵出的血液量", "核心概念", 4),
        ("心率", ["heart rate"], "每分钟心脏跳动的次数", "表现", 3),
        ("搏出量", ["stroke volume"], "心脏每次收缩射出的血量", "核心概念", 3),
    ],
    ("book_03", "sec_vessel"): [
        ("血压", ["blood pressure"], "血管内血液对血管壁的侧压力", "核心概念", 4),
        ("动脉血压", ["arterial pressure"], "主动脉内的血压，受心输出量和外周阻力影响", "核心概念", 4),
        ("微循环", ["microcirculation"], "微动脉与微静脉之间的血液循环", "结构", 3),
        ("外周阻力", ["peripheral resistance"], "小动脉和微动脉对血流的阻力", "机制", 3),
    ],
    ("book_07", "sec_inflame_pp_mediator"): [
        ("肿瘤坏死因子", ["TNF-alpha"], "主要由巨噬细胞产生的促炎细胞因子", "机制", 4),
        ("白细胞介素-1", ["IL-1"], "参与炎症和免疫调节的关键细胞因子", "机制", 4),
        ("NF-κB通路", ["NF-kappaB pathway"], "调控炎症相关基因表达的重要转录因子通路", "机制", 3),
        ("活性氧", ["reactive oxygen species", "ROS"], "氧化应激产生的自由基，参与细胞损伤和炎症信号", "机制", 3),
    ],
    ("book_07", "sec_inflame_pp_sys"): [
        ("SIRS", ["systemic inflammatory response syndrome"], "全身炎症反应综合征，严重感染或创伤引起的全身性炎症", "疾病", 5),
        ("急性期反应", ["acute phase response"], "炎症时肝脏合成急性期蛋白增加的保护性反应", "机制", 4),
        ("C反应蛋白", ["CRP"], "急性期反应中显著升高的血浆蛋白标志物", "表现", 3),
    ],
    ("book_07", "sec_fever_mech"): [
        ("致热原", ["pyrogen"], "能引起发热的物质，包括外源性和内源性致热原", "病原体", 4),
        ("体温调定点", ["set point"], "下丘脑体温调节中枢设定的体温参考值", "核心概念", 4),
        ("前列腺素E2", ["PGE2"], "介导致热原引起体温调定点上移的关键介质", "机制", 3),
    ],
}

total_nodes = 0
total_edges = 0

# ── Create chapter topics ──
for bid, chapters in CHAPTER_TOPICS.items():
    book_title = BOOKS[bid][0]
    for ch_id, ch_name, ch_def, ch_obj in chapters:
        cid = mkid(bid, ch_id)
        db.merge(KnowledgeNode(
            id=cid, name=ch_name, aliases=[], definition=ch_def,
            category="核心概念", importance=4,
            textbook_id=bid, textbook_title=book_title,
            chapter_title=ch_name, page=1, page_start=1, page_end=1,
            source_paragraph=ch_def, source_sentences=[ch_def],
            granularity="chapter_topic",
            learning_objective=ch_obj,
            quality_score=0.90, confidence=0.90,
            node_role="chapter", display_level="overview",
            created_by=SEED, source_type="demo_seed",
        ))
        total_nodes += 1

# ── Create section topics ──
for (bid, ch_id), sections in SECTION_TOPICS.items():
    book_title = BOOKS[bid][0]
    parent_cid = mkid(bid, ch_id)
    for sec_id, sec_name, sec_scope in sections:
        sid = mkid(bid, sec_id)
        db.merge(KnowledgeNode(
            id=sid, name=sec_name, aliases=[], definition=sec_scope,
            category="核心概念", importance=3,
            textbook_id=bid, textbook_title=book_title,
            chapter_title=ch_id, page=1, page_start=1, page_end=1,
            source_paragraph=sec_scope, source_sentences=[sec_scope],
            granularity="section_topic",
            learning_objective=sec_scope,
            quality_score=0.85, confidence=0.85,
            node_role="section", display_level="normal",
            parent_id=parent_cid,
            created_by=SEED, source_type="demo_seed",
        ))
        total_nodes += 1
        # Chapter contains section
        db.add(KnowledgeEdge(
            id=f"edge_{uuid.uuid4().hex[:10]}",
            source=parent_cid, target=sid,
            relation_type="contains",
            description=f"「{parent_cid.split('_')[-1]}」包含「{sec_name}」",
            confidence=0.95,
            relation_subtype="part_of",
            created_by=SEED,
        ))
        total_edges += 1

# ── Create core concepts ──
for (bid, sec_id), concepts in CORE_CONCEPTS.items():
    book_title = BOOKS[bid][0]
    parent_sid = mkid(bid, sec_id)
    for i, (name, aliases, defn, category, importance) in enumerate(concepts):
        cid = mkid(bid, f"cc_{sec_id}_{i:02d}")
        db.merge(KnowledgeNode(
            id=cid, name=name, aliases=aliases, definition=defn,
            category=category, importance=importance,
            textbook_id=bid, textbook_title=book_title,
            chapter_title=sec_id, page=1, page_start=1, page_end=1,
            source_paragraph=defn, source_sentences=[defn],
            granularity="core_concept",
            learning_objective=f"理解{name}的定义、机制和临床意义",
            quality_score=0.80, confidence=0.80,
            node_role="concept", display_level="normal",
            parent_id=parent_sid,
            created_by=SEED, source_type="demo_seed",
        ))
        total_nodes += 1
        # Section contains concept
        db.add(KnowledgeEdge(
            id=f"edge_{uuid.uuid4().hex[:10]}",
            source=parent_sid, target=cid,
            relation_type="contains",
            description=f"「{parent_sid.split('_')[-1]}」包含「{name}」",
            confidence=0.90,
            relation_subtype="part_of",
            created_by=SEED,
        ))
        total_edges += 1

# ── Generate cross-concept relations ──
CROSS_EDGES = [
    # Within 病理学 - 炎症
    ("book_05_ch_inflame", "book_05_cc_sec_inflame_alter_00", "book_05_cc_sec_inflame_exudate_00", "parallel", "变质与渗出为炎症的并行病理变化"),
    ("book_05_ch_inflame", "book_05_cc_sec_inflame_alter_00", "book_05_cc_sec_inflame_alter_01", "parallel", "变质与增生为炎症不同阶段的变化"),
    ("book_05_ch_inflame", "book_05_cc_sec_inflame_def_01", "book_05_cc_sec_inflame_exudate_02", "prerequisite", "变质（变性坏死）可触发渗出过程"),
    ("book_05_ch_inflame", "book_05_cc_sec_inflame_mediator_00", "book_05_cc_sec_inflame_exudate_00", "applies_to", "组胺介导血管反应参与渗出"),
    # 病理学 - 细胞损伤 → 炎症
    ("book_05_ch_inflame", "book_05_cc_sec_injury_mech_00", "book_05_cc_sec_inflame_def_01", "prerequisite", "ATP耗竭导致的细胞变性可引发炎症"),
    ("book_05_ch_inflame", "book_05_cc_sec_injury_mech_01", "book_05_cc_sec_inflame_mediator_02", "applies_to", "氧化应激激活NF-κB促进炎症细胞因子释放"),
    # 生理学 - 细胞功能
    ("book_03_ch_cell", "book_03_cc_sec_rest_pot_00", "book_03_cc_sec_action_pot_00", "prerequisite", "静息电位是理解动作电位的前置知识"),
    ("book_03_ch_cell", "book_03_cc_sec_rest_pot_02", "book_03_cc_sec_action_pot_00", "applies_to", "离子通道是产生动作电位的结构基础"),
    ("book_03_ch_cell", "book_03_cc_sec_action_pot_01", "book_03_cc_sec_action_pot_02", "parallel", "去极化与复极化为动作电位的两个阶段"),
    # 生理学 - 血液循环
    ("book_03_ch_circ", "book_03_cc_sec_heart_00", "book_03_cc_sec_heart_01", "contains", "心动周期包含心输出量的决定因素"),
    ("book_03_ch_circ", "book_03_cc_sec_vessel_00", "book_03_cc_sec_heart_01", "parallel", "血压与心输出量同为循环功能核心指标"),
    # 病理生理学 - 炎症
    ("book_07_ch_inflame_pp", "book_07_cc_sec_inflame_pp_mediator_00", "book_07_cc_sec_inflame_pp_sys_00", "applies_to", "TNF-α过量可导致SIRS"),
    ("book_07_ch_inflame_pp", "book_07_cc_sec_inflame_pp_mediator_03", "book_07_cc_sec_inflame_pp_mediator_02", "prerequisite", "活性氧可激活NF-κB通路"),
    # 病理生理学 - 发热
    ("book_07_ch_fever", "book_07_cc_sec_fever_mech_00", "book_07_cc_sec_fever_mech_01", "applies_to", "致热原使体温调定点上移"),
    ("book_07_ch_fever", "book_07_cc_sec_fever_mech_02", "book_07_cc_sec_fever_mech_00", "applies_to", "PGE2是内源性致热原的关键效应分子"),
    # Cross-textbook: 病理学 ↔ 病理生理学
    ("", "book_05_cc_sec_inflame_def_00", "book_07_cc_sec_inflame_pp_mediator_00", "parallel", "炎症在病理学与病理生理学中的互补描述"),
    ("", "book_07_cc_sec_inflame_pp_sys_00", "book_05_cc_sec_inflame_def_00", "applies_to", "SIRS是严重炎症的全身表现"),
    # Cross-textbook: 生理学 ↔ 病理生理学
    ("", "book_03_cc_sec_action_pot_00", "book_07_cc_sec_inflame_pp_mediator_02", "applies_to", "细胞电活动异常可触发炎症信号通路"),
    # Cross-textbook: 病理学 ↔ 生理学
    ("", "book_05_cc_sec_inflame_exudate_00", "book_03_cc_sec_vessel_00", "applies_to", "炎症血管反应涉及血压和微循环改变"),
]

cross_tb_sources = {"book_05_cc_sec_inflame_def_00", "book_07_cc_sec_inflame_pp_sys_00",
                    "book_03_cc_sec_action_pot_00", "book_05_cc_sec_inflame_exudate_00"}
for _, src, tgt, rtype, desc in CROSS_EDGES:
    db.add(KnowledgeEdge(
        id=f"edge_{uuid.uuid4().hex[:10]}",
        source=src, target=tgt,
        relation_type=rtype,
        description=desc,
        confidence=0.75,
        relation_subtype="sibling_of" if rtype == "parallel" else "",
        created_by=SEED,
        is_cross_textbook=(src in cross_tb_sources),
    ))
    total_edges += 1

# ── Integration decisions ──
DECISIONS = [
    ("dec_inflame_merge", "merge", ["book_05_cc_sec_inflame_def_00", "book_07_cc_sec_inflame_pp_mediator_00"],
     "炎症", "病理学和病理生理学对炎症的定义等价，均指活体组织对损伤的防御反应。合并为统一概念，病理学提供形态学描述，病理生理学补充分子机制。",
     0.92, 0.95, 0.88, 0.85),
    ("dec_cell_injury_link", "keep", ["book_05_cc_sec_injury_mech_00", "book_03_cc_sec_rest_pot_00"],
     "ATP耗竭 / 静息电位", "ATP耗竭影响钠钾泵功能进而影响静息电位，两概念为prerequisite关系不能合并。保留为独立节点并建立前置依赖。",
     0.38, 0.62, 0.80, 0.88),
    ("dec_cross_inflame", "keep", ["book_05_cc_sec_inflame_def_00", "book_03_cc_sec_vessel_00"],
     "炎症 / 血压", "炎症与血压为不同类别（机制 vs 核心概念），但存在applies_to关系。炎症导致血管通透性增加，影响血压调节。",
     0.25, 0.40, 0.75, 0.82),
    ("dec_tnf_sirs", "keep", ["book_07_cc_sec_inflame_pp_mediator_00", "book_07_cc_sec_inflame_pp_sys_00"],
     "TNF-α / SIRS", "TNF-α为机制类，SIRS为疾病类，类别不同不能合并。保持独立并建立applies_to关系。",
     0.42, 0.55, 0.90, 0.94),
]

for did, action, nodes, name, reason, sim_name, sim_def, sim_ctx, conf in DECISIONS:
    db.merge(IntegrationDecision(
        id=did, action=action, affected_nodes=nodes,
        result_name=name, reason=reason, confidence=conf,
        similarity_name=sim_name, similarity_definition=sim_def,
        similarity_context=sim_ctx,
        evidence=[{"quote": "demo", "source": "demo"}],
        alternatives_considered=["merge", "keep"],
        rejected_alternatives_reason="类别或定义不等价，不满足合并条件" if action == "keep" else "",
        risk="低风险" if conf > 0.85 else "建议教师复核",
        decision_effect=f"该{action}决策有助于形成完整的学习链路",
        created_by=SEED,
        teacher_override=False,
    ))

db.commit()
print(f"[SEED] {total_nodes} nodes ({len(CHAPTER_TOPICS)*3} chapters × sections), {total_edges} edges, {len(DECISIONS)} decisions")
print(f"  chapter_topic: {sum(len(v) for v in CHAPTER_TOPICS.values())}")
print(f"  section_topic: {sum(len(v) for v in SECTION_TOPICS.values())}")
print(f"  core_concept: {sum(len(v) for v in CORE_CONCEPTS.values())}")
db.close()
