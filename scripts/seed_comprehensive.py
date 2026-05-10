"""
Comprehensive layered knowledge graph for all 7 textbooks.
Target: 50-80 nodes per book, full contains/prerequisite/parallel/applies_to edges.
Chapter -> Section -> CoreConcept structure with proper medical knowledge.
"""
import sys, os, uuid, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/medessence.db")

from backend.database import SessionLocal, Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Chapter, Chunk, init_db

def mkid(prefix, *parts):
    return f"{prefix}_" + "_".join(str(p).replace(" ", "_") for p in parts)

init_db()
db = SessionLocal()

# Clean all existing graph data
db.query(KnowledgeEdge).delete()
db.query(KnowledgeNode).delete()
db.query(IntegrationDecision).delete()
db.query(Chunk).delete()
db.query(Chapter).delete()
db.query(Textbook).delete()
db.flush()

SEED = "comprehensive_seed"
total_n, total_e, total_d = 0, 0, 0

# ── Complete textbook data with chapters, sections, concepts ──
# Data structure: {book_id: (title, pages, [(ch_id, ch_name, ch_def, ch_obj, [(sec_id, sec_name, sec_scope, [(name, aliases, defn, cat, imp), ...]), ...]), ...])}

DATA = {
    "book_05": ("病理学", 418, [
        ("ch_inflame", "炎症", "具有血管系统的活体组织对损伤因子发生的防御性反应，基本病理变化包括变质、渗出和增生",
         "掌握炎症的概念、基本病理变化、炎症介质和临床意义", [
            ("sec_inflame_def", "炎症的定义与特征", "炎症的概念、原因、分类和五大临床特征：红、肿、热、痛、功能障碍", [
                ("炎症", ["inflammation"], "具有血管系统的活体组织对损伤因子发生的防御性反应", "核心概念", 5),
                ("变质", ["alteration"], "炎症局部组织发生的变性和坏死，是炎症最早期的变化", "机制", 4),
                ("渗出", ["exudation"], "炎症局部血管内液体和细胞成分通过血管壁进入组织间隙的过程", "机制", 5),
                ("增生", ["proliferation"], "炎症后期以修复为主的细胞增殖和间质增生过程", "机制", 4),
                ("趋化作用", ["chemotaxis"], "白细胞沿化学浓度梯度向炎症灶定向移动的现象", "机制", 3),
                ("吞噬作用", ["phagocytosis"], "巨噬细胞和中性粒细胞识别、吞噬和消化病原体及坏死碎片", "机制", 4),
            ]),
            ("sec_inflame_exudate", "渗出与血管反应", "炎症时血管扩张、通透性增加、白细胞游出和吞噬的完整过程", [
                ("血管反应", ["vascular response"], "炎症介质引起微血管扩张、血流速度改变和通透性增高的过程", "机制", 4),
                ("血管通透性增高", ["vascular permeability"], "内皮细胞收缩和损伤导致血浆蛋白和液体渗出的机制", "机制", 3),
                ("白细胞游出", ["leukocyte emigration"], "白细胞通过黏附、滚动、游出等步骤穿过血管壁进入组织", "机制", 4),
                ("白细胞黏附", ["leukocyte adhesion"], "选择素和整合素介导的白细胞与内皮细胞相互作用", "机制", 3),
                ("液体渗出", ["fluid exudation"], "富含蛋白质的液体进入组织间隙形成炎性水肿", "机制", 3),
            ]),
            ("sec_inflame_mediator", "炎症介质", "参与炎症反应的各种化学介质，包括细胞来源和血浆来源两大类", [
                ("组胺", ["histamine"], "肥大细胞和嗜碱性粒细胞释放的血管活性胺，引起血管扩张和通透性增加", "机制", 3),
                ("补体系统", ["complement system"], "血浆蛋白级联激活系统，参与趋化、调理、溶菌和炎症", "机制", 4),
                ("细胞因子", ["cytokines"], "IL-1、TNF、IL-6等由免疫细胞分泌的信号分子，介导炎症和免疫", "机制", 4),
                ("前列腺素", ["prostaglandin"], "花生四烯酸代谢产物，参与血管扩张、发热和疼痛", "机制", 3),
                ("白三烯", ["leukotrienes"], "花生四烯酸脂氧合酶代谢产物，强效趋化因子和支气管收缩剂", "机制", 3),
                ("血小板活化因子", ["PAF"], "多种细胞产生的磷脂介质，促进血小板聚集和白细胞活化", "机制", 2),
                ("激肽系统", ["kinin system"], "缓激肽等引起血管扩张、疼痛和通透性增高的血浆蛋白酶系统", "机制", 3),
                ("活性氧", ["reactive oxygen species"], "中性粒细胞呼吸爆发产生的自由基，杀菌但也引起组织损伤", "机制", 3),
            ]),
            ("sec_inflame_outcome", "炎症的结局", "炎症消退、迁延不愈和转为慢性的机制与条件", [
                ("急性炎症", ["acute inflammation"], "起病急、持续时间短的炎症，以渗出和中性粒细胞浸润为主", "疾病", 4),
                ("慢性炎症", ["chronic inflammation"], "持续时间长的炎症，以淋巴细胞和巨噬细胞浸润及组织增生为特征", "疾病", 4),
                ("肉芽肿性炎", ["granulomatous inflammation"], "由巨噬细胞聚集形成肉芽肿为特征的慢性炎症", "疾病", 4),
                ("脓肿", ["abscess"], "局限性化脓性炎症，形成充满脓液的腔", "疾病", 3),
            ]),
        ]),
        ("ch_injury", "细胞损伤", "细胞在内外环境改变时发生的代谢、功能和形态改变", "掌握细胞损伤的原因、机制和形态学表现", [
            ("sec_injury_mech", "细胞损伤机制", "ATP耗竭、氧化应激、钙超载、膜损伤和线粒体功能障碍", [
                ("ATP耗竭", ["ATP depletion"], "缺氧或线粒体损伤导致细胞能量代谢障碍", "机制", 4),
                ("氧化应激", ["oxidative stress"], "活性氧产生过多或抗氧化能力不足导致的细胞损伤", "机制", 4),
                ("钙超载", ["calcium overload"], "细胞内Ca2+浓度异常升高激活磷脂酶、蛋白酶和核酸内切酶", "机制", 3),
                ("膜损伤", ["membrane damage"], "细胞膜完整性丧失、离子梯度破坏和细胞内容物外泄", "机制", 3),
                ("线粒体损伤", ["mitochondrial damage"], "线粒体通透性转换孔开放、细胞色素c释放和能量产生障碍", "机制", 3),
                ("蛋白质错误折叠", ["protein misfolding"], "内质网应激导致未折叠蛋白积累和细胞功能障碍", "机制", 2),
            ]),
            ("sec_injury_type", "可逆与不可逆损伤", "细胞损伤从变性到坏死的演进过程及形态学鉴别", [
                ("变性", ["degeneration"], "细胞代谢障碍导致的可逆性形态学改变", "机制", 3),
                ("坏死", ["necrosis"], "细胞不可逆损伤后的被动性死亡，伴随炎症反应", "机制", 5),
                ("凋亡", ["apoptosis"], "基因调控的程序性细胞死亡，不引起炎症", "机制", 5),
                ("凝固性坏死", ["coagulative necrosis"], "细胞轮廓保存、组织呈灰白色固体的坏死类型", "机制", 3),
                ("液化性坏死", ["liquefactive necrosis"], "组织溶解形成液体状坏死物，常见于脑组织", "机制", 3),
                ("干酪样坏死", ["caseous necrosis"], "结核病的特征性坏死，呈奶酪样外观", "机制", 3),
            ]),
            ("sec_repair", "组织修复", "组织损伤后的再生、肉芽组织形成和瘢痕修复", [
                ("再生", ["regeneration"], "由同种细胞增殖完成的组织修复，恢复原有结构和功能", "机制", 4),
                ("纤维性修复", ["fibrosis"], "由纤维结缔组织增生替代损伤组织，形成瘢痕", "机制", 3),
                ("肉芽组织", ["granulation tissue"], "新生毛细血管和成纤维细胞构成的修复组织", "结构", 4),
                ("伤口愈合", ["wound healing"], "创伤后炎症、增生和重塑三个阶段的组织修复过程", "机制", 3),
                ("一期愈合", ["primary healing"], "创缘整齐、感染少的伤口直接愈合方式", "机制", 2),
            ]),
        ]),
        ("ch_tumor", "肿瘤", "机体在各种致瘤因素作用下局部组织细胞异常增生形成的新生物",
         "掌握肿瘤的基本概念、分类命名、良恶性鉴别和病因", [
            ("sec_tumor_concept", "肿瘤概念", "肿瘤的定义、命名原则和基本特征", [
                ("肿瘤", ["tumor", "neoplasm"], "机体在各种致瘤因素作用下局部组织细胞异常增生形成的新生物", "核心概念", 5),
                ("良性肿瘤", ["benign tumor"], "分化程度高、生长缓慢、不转移的肿瘤", "疾病", 4),
                ("恶性肿瘤", ["malignant tumor"], "分化程度低、生长迅速、可侵袭和转移的肿瘤", "疾病", 5),
                ("癌", ["carcinoma"], "来源于上皮组织的恶性肿瘤", "疾病", 4),
                ("肉瘤", ["sarcoma"], "来源于间叶组织的恶性肿瘤", "疾病", 4),
                ("异型性", ["atypia"], "肿瘤细胞在形态和结构上与其来源正常组织的差异程度", "核心概念", 3),
                ("肿瘤分级", ["grading"], "根据分化程度和恶性程度对肿瘤进行的病理学分级", "诊断", 3),
            ]),
            ("sec_tumor_spread", "肿瘤生长与扩散", "肿瘤的侵袭、转移途径及其分子机制", [
                ("侵袭", ["invasion"], "肿瘤细胞突破基底膜向周围组织浸润的过程", "机制", 4),
                ("转移", ["metastasis"], "肿瘤细胞从原发部位经淋巴道、血道或体腔到达远处继续生长", "机制", 5),
                ("淋巴道转移", ["lymphatic metastasis"], "肿瘤细胞经淋巴管到达区域淋巴结的转移方式", "机制", 3),
                ("血道转移", ["hematogenous metastasis"], "肿瘤细胞经血管到达远处器官的转移方式", "机制", 3),
                ("肿瘤血管生成", ["angiogenesis"], "肿瘤诱导新生血管形成以满足其生长代谢需求", "机制", 3),
            ]),
            ("sec_tumor_cause", "肿瘤病因", "化学、物理、生物致癌因素及其致癌机制", [
                ("化学致癌", ["chemical carcinogenesis"], "多环芳烃、亚硝胺、黄曲霉毒素等化学物质的致癌作用", "机制", 3),
                ("原癌基因", ["proto-oncogene"], "正常细胞中存在的促进细胞增殖的基因，突变后成为癌基因", "机制", 4),
                ("抑癌基因", ["tumor suppressor gene"], "抑制细胞过度增殖的基因，如p53、Rb，失活后促进肿瘤发生", "机制", 4),
                ("DNA修复基因", ["DNA repair gene"], "维持基因组稳定性的基因，缺陷导致突变积累和肿瘤易感性增高", "机制", 3),
            ]),
        ]),
    ]),
    "book_03": ("生理学", 450, [
        ("ch_cell", "细胞的基本功能", "细胞膜的物质转运、信号转导和生物电活动", "掌握静息电位和动作电位的产生机制及其生理意义", [
            ("sec_membrane", "细胞膜结构与物质转运", "细胞膜的液态镶嵌模型和跨膜物质转运方式", [
                ("单纯扩散", ["simple diffusion"], "脂溶性小分子顺浓度梯度通过细胞膜的转运方式", "机制", 3),
                ("易化扩散", ["facilitated diffusion"], "亲水性分子经载体蛋白或通道蛋白顺浓度梯度的被动转运", "机制", 3),
                ("主动转运", ["active transport"], "消耗ATP逆浓度梯度的跨膜转运,如钠钾泵", "机制", 4),
                ("钠钾泵", ["Na+/K+ ATPase"], "每消耗1ATP泵出3Na+泵入2K+,维持细胞内外离子浓度梯度", "结构", 4),
                ("继发性主动转运", ["secondary active transport"], "利用钠离子浓度势能驱动其他物质逆浓度转运", "机制", 3),
                ("出胞与入胞", ["exocytosis endocytosis"], "大分子物质通过膜包裹囊泡进出细胞的转运方式", "机制", 2),
            ]),
            ("sec_bioelectric", "生物电活动", "静息电位和动作电位的产生机制、特征和传导", [
                ("静息电位", ["resting potential"], "细胞在安静状态下膜两侧的内负外正电位差，主要由K+平衡电位决定", "核心概念", 5),
                ("动作电位", ["action potential"], "可兴奋细胞受刺激时产生的快速可逆膜电位变化", "核心概念", 5),
                ("阈电位", ["threshold potential"], "触发动作电位所需的最小去极化电位水平", "核心概念", 3),
                ("去极化", ["depolarization"], "膜电位向正值方向变化，主要由电压门控Na+通道开放引起", "机制", 4),
                ("复极化", ["repolarization"], "膜电位恢复到静息水平，主要由电压门控K+通道开放引起", "机制", 4),
                ("不应期", ["refractory period"], "动作电位后钠通道失活导致细胞暂时丧失兴奋性的时期", "机制", 3),
                ("局部电位", ["local potential"], "阈下刺激引起的不能远传的局部膜电位变化", "机制", 3),
            ]),
            ("sec_signal", "细胞信号转导", "受体、G蛋白、第二信使和细胞内信号通路", [
                ("G蛋白耦联受体", ["GPCR"], "七次跨膜受体,通过激活G蛋白启动胞内信号级联", "结构", 4),
                ("第二信使", ["second messenger"], "cAMP、IP3、DAG、Ca2+等介导胞内信号放大的小分子", "机制", 3),
                ("cAMP-PKA通路", ["cAMP pathway"], "腺苷酸环化酶催化ATP生成cAMP,激活蛋白激酶A", "机制", 3),
                ("酪氨酸激酶受体", ["RTK"], "配体结合后自身磷酸化并激活下游Ras-MAPK等信号通路", "结构", 4),
                ("钙离子信号", ["calcium signaling"], "Ca2+作为第二信使参与肌肉收缩、神经递质释放等", "机制", 3),
            ]),
        ]),
        ("ch_circ", "血液循环", "心脏泵血、血管生理和心血管活动的调节", "理解心脏泵血机制、血压形成和心血管调节", [
            ("sec_heart", "心脏泵血功能", "心动周期、心输出量、心肌收缩性和心泵调节", [
                ("心动周期", ["cardiac cycle"], "心脏一次收缩和舒张的完整过程，包括等容收缩、射血、等容舒张和充盈", "核心概念", 4),
                ("心输出量", ["cardiac output"], "每分钟一侧心室泵出的血量=搏出量×心率", "核心概念", 4),
                ("搏出量", ["stroke volume"], "心脏每次收缩射出的血量，受前负荷、后负荷和收缩力影响", "核心概念", 4),
                ("心率", ["heart rate"], "每分钟心脏跳动的次数，受自主神经和体液因素调节", "表现", 3),
                ("射血分数", ["ejection fraction"], "搏出量占心室舒张末期容积的百分比，反映心泵效率", "表现", 3),
            ]),
            ("sec_vessel", "血管生理", "血流动力学、血压、微循环和静脉回流", [
                ("血压", ["blood pressure"], "血管内血液对血管壁的侧压力，通常指动脉血压", "核心概念", 5),
                ("收缩压", ["systolic pressure"], "心室收缩时动脉血压的最高值", "表现", 3),
                ("舒张压", ["diastolic pressure"], "心室舒张时动脉血压的最低值", "表现", 3),
                ("外周阻力", ["peripheral resistance"], "小动脉和微动脉对血流的阻力，是舒张压的主要决定因素", "机制", 4),
                ("微循环", ["microcirculation"], "微动脉与微静脉之间的血液循环，执行物质交换功能", "结构", 3),
            ]),
            ("sec_cv_reg", "心血管调节", "神经调节、体液调节和自身调节", [
                ("压力感受性反射", ["baroreceptor reflex"], "颈动脉窦和主动脉弓压力感受器介导的心血管快速调节", "机制", 4),
                ("肾素-血管紧张素系统", ["RAS"], "肾脏球旁细胞分泌肾素,激活血管紧张素-醛固酮系统调节血压", "机制", 4),
                ("交感神经", ["sympathetic nerve"], "释放去甲肾上腺素,增加心率和心肌收缩力,收缩血管", "机制", 3),
                ("迷走神经", ["vagus nerve"], "释放乙酰胆碱,减慢心率,降低房室传导速度", "机制", 3),
            ]),
        ]),
        ("ch_resp", "呼吸", "外呼吸(肺通气与肺换气)、气体运输和内呼吸", "理解呼吸运动、肺通气原理和呼吸调节", [
            ("sec_pulmonary", "肺通气", "呼吸运动、肺内压变化和气道阻力", [
                ("肺通气", ["pulmonary ventilation"], "肺与外界环境之间的气体交换过程", "核心概念", 4),
                ("潮气量", ["tidal volume"], "每次平静呼吸时吸入或呼出的气体量", "表现", 3),
                ("肺活量", ["vital capacity"], "最大吸气后尽力呼出的最大气体量", "表现", 3),
                ("肺泡表面活性物质", ["pulmonary surfactant"], "降低肺泡表面张力、防止肺泡萎陷的磷脂蛋白复合物", "机制", 3),
                ("顺应性", ["compliance"], "单位压力变化引起的肺容积变化，反映肺扩张能力", "表现", 3),
            ]),
            ("sec_gas_exchange", "气体交换与运输", "肺换气、组织换气和O2/CO2的血液运输", [
                ("氧解离曲线", ["oxygen dissociation curve"], "反映血氧饱和度与氧分压关系的S形曲线", "核心概念", 4),
                ("氧合血红蛋白", ["oxyhemoglobin"], "O2与血红蛋白中亚铁离子可逆结合形成的复合物", "机制", 3),
                ("CO2运输", ["CO2 transport"], "CO2以溶解、碳酸氢盐和氨基甲酸血红蛋白形式运输", "机制", 3),
                ("波尔效应", ["Bohr effect"], "pH降低或CO2升高使氧解离曲线右移，促进O2释放", "机制", 3),
            ]),
        ]),
    ]),
    "book_07": ("病理生理学", 291, [
        ("ch_inflame_pp", "炎症的病理生理", "炎症的病理生理机制，包括炎症介质网络和全身反应",
         "掌握炎症介质的协同作用、炎症的全身反应和多器官功能障碍", [
            ("sec_mediator_pp", "炎症介质网络", "细胞因子网络、趋化因子和炎症信号转导通路", [
                ("TNF-α", ["tumor necrosis factor"], "主要由巨噬细胞产生，诱导发热、急性期反应和细胞凋亡", "机制", 4),
                ("IL-1", ["interleukin-1"], "参与发热、急性期反应和淋巴细胞活化的关键促炎因子", "机制", 4),
                ("IL-6", ["interleukin-6"], "促进急性期蛋白合成和B细胞分化的多效细胞因子", "机制", 3),
                ("NF-κB通路", ["NF-kappaB"], "调控炎症、免疫和细胞存活基因表达的核心转录因子", "机制", 4),
                ("趋化因子", ["chemokines"], "引导白细胞迁移和定位的小分子细胞因子家族", "机制", 3),
            ]),
            ("sec_SIRS", "全身炎症反应", "SIRS、脓毒症和MODS的病理生理机制", [
                ("SIRS", ["systemic inflammatory response syndrome"], "严重感染或创伤引起的全身性炎症反应综合征", "疾病", 5),
                ("脓毒症", ["sepsis"], "感染引起的宿主反应失调导致的危及生命的器官功能障碍", "疾病", 5),
                ("MODS", ["multiple organ dysfunction syndrome"], "严重创伤或感染后序贯发生的多器官功能障碍", "疾病", 4),
                ("急性期反应", ["acute phase response"], "炎症时肝脏合成CRP等急性期蛋白的保护性反应", "机制", 3),
                ("C反应蛋白", ["CRP"], "急性期显著升高的血浆蛋白，炎症和感染的重要标志物", "表现", 3),
            ]),
        ]),
        ("ch_fever", "发热", "发热的发生机制、分期和机体代谢功能变化", "理解致热原、体温调定点上移和发热的临床处理原则", [
            ("sec_fever_mech", "发热机制", "外源性和内源性致热原的作用机制", [
                ("致热原", ["pyrogen"], "能引起体温调定点上移导致发热的物质", "病原体", 4),
                ("体温调定点", ["set point"], "下丘脑视前区体温调节中枢设定的体温参考值", "核心概念", 4),
                ("PGE2", ["prostaglandin E2"], "花生四烯酸环氧合酶代谢产物，介导致热原的发热效应", "机制", 3),
                ("内源性致热原", ["endogenous pyrogen"], "IL-1、TNF、IL-6等由免疫细胞产生并能引起发热的细胞因子", "病原体", 4),
                ("外源性致热原", ["exogenous pyrogen"], "细菌内毒素LPS等来自体外的致热物质", "病原体", 3),
            ]),
            ("sec_fever_phase", "发热分期", "体温上升期、高热持续期和退热期的特征", [
                ("体温上升期", ["chill phase"], "体温调定点上移后产热增加散热减少导致的体温升高阶段", "机制", 3),
                ("高热持续期", ["fever plateau"], "体温维持在新调定点水平的平衡阶段", "表现", 3),
                ("退热期", ["defervescence"], "致热原消除后调定点下移散热增加导致的体温下降阶段", "表现", 3),
            ]),
        ]),
        ("ch_shock", "休克", "休克的病因、分类、微循环变化和器官功能障碍", "掌握休克的微循环变化三个阶段和器官保护策略", [
            ("sec_shock_type", "休克类型", "低血容量性、心源性、分布性和梗阻性休克的病因", [
                ("低血容量性休克", ["hypovolemic shock"], "血容量减少导致的休克，如失血、脱水", "疾病", 4),
                ("心源性休克", ["cardiogenic shock"], "心脏泵功能衰竭导致的心输出量不足", "疾病", 4),
                ("感染性休克", ["septic shock"], "严重感染引起的分布性休克伴器官功能障碍", "疾病", 5),
            ]),
            ("sec_shock_mech", "休克微循环变化", "缺血缺氧期、淤血缺氧期和微循环衰竭期", [
                ("微循环缺血期", ["ischemic phase"], "交感-肾上腺髓质系统兴奋导致微血管收缩和组织缺血", "机制", 4),
                ("微循环淤血期", ["stagnant phase"], "代谢产物堆积导致微血管扩张和血液淤滞", "机制", 4),
                ("微循环衰竭期", ["refractory phase"], "微血管麻痹、DIC和不可逆细胞损伤", "机制", 3),
                ("DIC", ["disseminated intravascular coagulation"], "弥散性血管内凝血，微循环内广泛微血栓形成", "疾病", 3),
            ]),
        ]),
    ]),
    "book_01": ("局部解剖学", 305, [
        ("ch_neck", "颈部", "颈部由皮肤、浅筋膜、深筋膜、肌群、血管神经和内脏器官组成",
         "掌握颈部分区、筋膜层次和主要血管神经走行", [
            ("sec_neck_fascia", "颈部筋膜层次", "颈浅筋膜、颈深筋膜浅层、中层（气管前层）和深层（椎前层）", [
                ("颈深筋膜", ["deep cervical fascia"], "颈部的深筋膜分为浅层(封套层)、中层(气管前层)和深层(椎前层)", "结构", 4),
                ("颈动脉鞘", ["carotid sheath"], "颈深筋膜中层形成的包裹颈总动脉、颈内静脉和迷走神经的筋膜管", "结构", 4),
                ("颈筋膜间隙", ["cervical fascial spaces"], "筋膜层之间的疏松结缔组织间隙，感染可沿其扩散", "结构", 3),
                ("胸锁乳突肌", ["sternocleidomastoid"], "颈部的重要肌性标志，起自胸骨锁骨止于乳突", "结构", 3),
            ]),
            ("sec_neck_vessel", "颈部血管神经", "颈总动脉、锁骨下动脉、颈内静脉和迷走神经、膈神经走行", [
                ("颈总动脉", ["common carotid artery"], "在甲状软骨上缘分为颈内和颈外动脉", "结构", 4),
                ("颈外动脉", ["external carotid artery"], "主要供应颈部和面部结构的动脉", "结构", 3),
                ("迷走神经", ["vagus nerve"], "走行于颈动脉鞘内，发出喉上神经和喉返神经", "结构", 4),
                ("膈神经", ["phrenic nerve"], "发自C3-5前支，走行于前斜角肌前面，支配膈肌运动", "结构", 3),
                ("臂丛", ["brachial plexus"], "C5-T1前支组成，经斜角肌间隙进入腋窝", "结构", 4),
            ]),
            ("sec_neck_viscera", "颈部内脏", "甲状腺、甲状旁腺、喉、气管颈段和咽的解剖", [
                ("甲状腺", ["thyroid gland"], "位于喉和气管前方的内分泌腺，分泌甲状腺激素", "结构", 4),
                ("喉返神经", ["recurrent laryngeal nerve"], "迷走神经分支，绕主动脉弓或锁骨下动脉返回支配喉肌", "结构", 3),
            ]),
        ]),
        ("ch_thorax", "胸部", "胸壁、胸膜腔和纵隔的结构，心肺大血管的解剖位置",
         "理解胸膜腔、纵隔分区和心肺大血管的精确解剖位置", [
            ("sec_thorax_wall", "胸壁", "肋骨、肋间肌、胸膜和胸内筋膜", [
                ("胸膜", ["pleura"], "覆盖在肺表面和胸壁内面的浆膜，分脏胸膜和壁胸膜", "结构", 4),
                ("胸膜腔", ["pleural cavity"], "脏壁胸膜之间的潜在性腔隙，正常情况下含少量浆液", "结构", 4),
                ("肋间隙", ["intercostal space"], "相邻肋骨之间的间隙，内含肋间肌和肋间血管神经束", "结构", 3),
                ("肋间神经", ["intercostal nerve"], "胸神经前支，沿肋沟走行，支配肋间肌和胸腹壁皮肤", "结构", 3),
            ]),
            ("sec_mediastinum", "纵隔", "上、前、中、后纵隔的划分和重要结构", [
                ("纵隔", ["mediastinum"], "两侧胸膜腔之间的区域，包含心、大血管、食管等重要结构", "结构", 4),
                ("上纵隔", ["superior mediastinum"], "包含主动脉弓、上腔静脉、气管、食管和胸导管等", "结构", 3),
                ("心包", ["pericardium"], "包裹心脏和大血管根部的纤维浆膜囊", "结构", 3),
                ("食管胸部", ["thoracic esophagus"], "经上纵隔和后纵隔下行穿过膈肌食管裂孔", "结构", 3),
                ("胸导管", ["thoracic duct"], "全身最大的淋巴管，起自乳糜池经主动脉裂孔入胸腔", "结构", 3),
            ]),
            ("sec_heart_anat", "心脏解剖", "心腔结构、心瓣膜位置和冠状动脉分布", [
                ("冠状动脉", ["coronary artery"], "左、右冠状动脉分别起自主动脉窦，供应心肌血液", "结构", 5),
                ("心瓣膜", ["heart valves"], "房室瓣和半月瓣维持血液单向流动", "结构", 4),
                ("窦房结", ["sinoatrial node"], "心脏正常起搏点，位于上腔静脉与右心房交界处", "结构", 4),
                ("室间隔", ["interventricular septum"], "分隔左右心室的肌性/膜性结构", "结构", 3),
            ]),
        ]),
    ]),
    "book_02": ("组织学与胚胎学", 319, [
        ("ch_epithelium", "上皮组织", "上皮组织由密集排列的细胞和少量细胞间质组成，分布在体表和体内腔面",
         "掌握各类上皮组织的结构特点、分布和功能", [
            ("sec_epi_type", "上皮组织分类", "被覆上皮、腺上皮和感觉上皮的结构与功能", [
                ("被覆上皮", ["covering epithelium"], "覆盖于体表或衬于体腔管腔内表面的上皮组织", "结构", 4),
                ("单层扁平上皮", ["simple squamous epithelium"], "一层扁平细胞组成，分布于内皮和间皮", "结构", 3),
                ("单层柱状上皮", ["simple columnar epithelium"], "一层柱状细胞组成，分布于胃肠道黏膜", "结构", 3),
                ("假复层纤毛柱状上皮", ["pseudostratified ciliated columnar epithelium"], "分布于呼吸道，含纤毛和杯状细胞", "结构", 3),
                ("复层扁平上皮", ["stratified squamous epithelium"], "多层细胞构成，表层细胞扁平，分布于皮肤和口腔", "结构", 3),
                ("变移上皮", ["transitional epithelium"], "细胞层次和形态随器官充盈状态而变，分布于泌尿道", "结构", 3),
                ("腺上皮", ["glandular epithelium"], "以分泌为主要功能的上皮组织", "结构", 3),
            ]),
            ("sec_epi_special", "上皮细胞特化结构", "微绒毛、纤毛、紧密连接、桥粒和缝隙连接", [
                ("微绒毛", ["microvilli"], "上皮细胞游离面的指状突起，增加吸收面积", "结构", 3),
                ("紧密连接", ["tight junction"], "相邻细胞膜外层融合封闭细胞间隙，维持屏障功能", "结构", 4),
                ("桥粒", ["desmosome"], "细胞间的锚定连接结构，提供机械强度", "结构", 3),
                ("缝隙连接", ["gap junction"], "细胞间的通道连接，允许小分子和离子直接通过", "结构", 3),
                ("基底膜", ["basement membrane"], "上皮基部的细胞外基质层，由基板和网板组成", "结构", 4),
            ]),
        ]),
        ("ch_connective", "结缔组织", "由细胞和大量细胞外基质组成，包括固有结缔组织、软骨和骨",
         "掌握结缔组织细胞类型、纤维成分和基质的组成", [
            ("sec_conn_cell", "结缔组织细胞", "成纤维细胞、巨噬细胞、肥大细胞、浆细胞和脂肪细胞", [
                ("成纤维细胞", ["fibroblast"], "合成胶原纤维、弹性纤维和基质的结缔组织主要细胞", "结构", 4),
                ("巨噬细胞", ["macrophage"], "由单核细胞分化而来，具有强大的吞噬病原体和抗原递呈能力", "结构", 4),
                ("肥大细胞", ["mast cell"], "胞质富含嗜碱性颗粒，释放组胺和肝素参与过敏反应", "结构", 3),
                ("胶原纤维", ["collagen fiber"], "由I型胶原蛋白组成，提供组织的抗拉强度", "结构", 4),
                ("弹性纤维", ["elastic fiber"], "由弹性蛋白组成，赋予组织弹性", "结构", 3),
                ("网状纤维", ["reticular fiber"], "III型胶原蛋白组成，构成实质器官的网状支架", "结构", 3),
            ]),
            ("sec_cartilage_bone", "软骨与骨", "透明软骨、弹性软骨、纤维软骨和骨组织的结构", [
                ("透明软骨", ["hyaline cartilage"], "最常见的软骨类型，分布于关节面、肋软骨和呼吸道", "结构", 4),
                ("骨单位", ["osteon"], "密质骨的基本结构单位，由中央管和同心排列的骨板组成", "结构", 4),
                ("破骨细胞", ["osteoclast"], "多核巨细胞，来源于单核细胞前体，参与骨吸收", "结构", 3),
                ("成骨细胞", ["osteoblast"], "合成和分泌骨基质蛋白的细胞，分化为骨细胞", "结构", 3),
            ]),
        ]),
        ("ch_blood", "血液", "血液由血浆和血细胞组成，是机体重要的结缔组织",
         "掌握各类血细胞的形态结构、功能和正常值", [
            ("sec_blood_cell", "血细胞", "红细胞、白细胞和血小板的形态结构和功能", [
                ("红细胞", ["erythrocyte"], "双凹圆盘状无核细胞，含血红蛋白运输O2和CO2", "结构", 4),
                ("中性粒细胞", ["neutrophil"], "数量最多的白细胞，核分叶，吞噬细菌和坏死组织", "结构", 4),
                ("淋巴细胞", ["lymphocyte"], "免疫核心细胞，分T、B和NK细胞，参与特异性免疫", "结构", 4),
                ("单核细胞", ["monocyte"], "最大的白细胞，分化为巨噬细胞参与吞噬和抗原递呈", "结构", 3),
                ("血小板", ["platelet"], "骨髓巨核细胞脱落的胞质片段，参与止血和凝血", "结构", 3),
            ]),
        ]),
    ]),
    "book_04": ("医学微生物学", 386, [
        ("ch_bacteria", "细菌学基础", "细菌的形态结构、生理代谢、遗传变异和感染机制",
         "掌握细菌细胞壁结构差异、革兰染色原理和细菌致病机制", [
            ("sec_bac_struct", "细菌结构", "细胞壁、细胞膜、核质、质粒、荚膜、鞭毛和芽孢", [
                ("革兰阳性菌", ["Gram-positive bacteria"], "细胞壁含厚肽聚糖层和磷壁酸，染色呈紫色", "结构", 5),
                ("革兰阴性菌", ["Gram-negative bacteria"], "细胞壁含薄肽聚糖层和外膜脂多糖，染色呈红色", "结构", 5),
                ("肽聚糖", ["peptidoglycan"], "由N-乙酰葡糖胺和N-乙酰胞壁酸交替组成的细菌细胞壁骨架", "结构", 4),
                ("脂多糖", ["LPS"], "革兰阴性菌外膜成分，脂质A为内毒素活性中心", "病原体", 4),
                ("荚膜", ["capsule"], "部分细菌合成的细胞壁外黏液层，具有抗吞噬和黏附作用", "结构", 3),
                ("芽孢", ["spore"], "某些革兰阳性菌在恶劣环境下形成的代谢休眠体", "结构", 3),
                ("鞭毛", ["flagellum"], "细菌的运动器官，由鞭毛蛋白组成，具有抗原性(H抗原)", "结构", 3),
                ("菌毛", ["pilus"], "细菌表面的蛋白丝状附属物，参与黏附和接合", "结构", 3),
            ]),
            ("sec_bac_infect", "细菌感染机制", "黏附、侵入、毒素产生和免疫逃逸", [
                ("内毒素", ["endotoxin"], "革兰阴性菌LPS成分，激活炎症反应导致发热和休克", "病原体", 5),
                ("外毒素", ["exotoxin"], "细菌分泌的蛋白质毒素，具有高度的组织特异性和毒性", "病原体", 5),
                ("侵袭力", ["invasiveness"], "细菌突破宿主防御屏障并在体内扩散的能力", "机制", 3),
                ("生物膜", ["biofilm"], "细菌黏附于表面形成的多糖蛋白复合物群落，高度耐药", "机制", 4),
                ("质粒", ["plasmid"], "细菌染色体外的环状DNA，可携带耐药基因和毒力基因", "结构", 3),
            ]),
        ]),
        ("ch_myco", "分枝杆菌属", "结核分枝杆菌和麻风分枝杆菌的生物学特性和致病机制",
         "掌握结核分枝杆菌的培养特性、抗酸染色和致病物质", [
            ("sec_tb", "结核分枝杆菌", "形态染色、培养特性、致病物质和免疫应答", [
                ("结核分枝杆菌", ["Mycobacterium tuberculosis"], "抗酸染色阳性、专性需氧的细长杆菌，引起结核病", "病原体", 5),
                ("抗酸染色", ["acid-fast stain"], "分枝杆菌特有的染色方法，利用其细胞壁蜡质抗酸性", "诊断", 4),
                ("索状因子", ["cord factor"], "结核分枝杆菌的毒力因子，破坏线粒体膜和抑制白细胞迁移", "病原体", 3),
                ("结核菌素试验", ["tuberculin test"], "用PPD皮内注射检测机体对结核菌的IV型超敏反应", "诊断", 3),
                ("BCG疫苗", ["BCG vaccine"], "减毒牛型结核分枝杆菌制成的活疫苗，预防结核病", "治疗", 3),
            ]),
        ]),
        ("ch_immunity", "抗感染免疫", "固有免疫和适应性免疫在抗感染中的作用", "理解抗体、补体和细胞免疫的抗感染机制", [
            ("sec_innate", "固有免疫", "皮肤黏膜屏障、吞噬细胞、补体和NK细胞的非特异性防御", [
                ("补体系统", ["complement system"], "血浆蛋白级联系统，经经典或旁路途径激活杀菌和调理", "机制", 4),
                ("溶菌酶", ["lysozyme"], "水解革兰阳性菌细胞壁肽聚糖的天然抗菌酶", "机制", 3),
                ("干扰素", ["interferon"], "病毒感染细胞分泌的细胞因子，诱导抗病毒状态", "机制", 3),
                ("抗原递呈", ["antigen presentation"], "APC以MHC分子递呈抗原肽供T细胞识别", "机制", 5),
                ("MHC分子", ["MHC molecule"], "主要组织相容性复合体分子，分I类和II类", "结构", 4),
            ]),
            ("sec_adaptive", "适应性免疫", "体液免疫(IgA/IgG/IgM)和细胞免疫(Th/Tc)的抗感染效应", [
                ("抗体", ["antibody"], "B细胞分泌的免疫球蛋白，特异性结合抗原中和病原", "机制", 4),
                ("IgG", ["immunoglobulin G"], "血清中含量最高的免疫球蛋白，可通过胎盘", "结构", 3),
                ("IgA", ["immunoglobulin A"], "黏膜分泌的免疫球蛋白，提供黏膜表面保护", "结构", 3),
                ("CD4+T细胞", ["CD4+ T cell"], "辅助性T细胞，识别MHC-II递呈抗原并激活巨噬细胞和B细胞", "结构", 4),
                ("CD8+T细胞", ["CD8+ T cell"], "细胞毒性T细胞，识别MHC-I递呈抗原并杀伤感染细胞", "结构", 4),
                ("免疫记忆", ["immunological memory"], "初次免疫应答后产生的记忆细胞赋予机体长期保护", "机制", 3),
            ]),
        ]),
    ]),
    "book_06": ("传染病学", 398, [
        ("ch_infect_basic", "感染病学基础", "感染的概念、感染过程、传染病流行三环节和预防策略",
         "掌握传染病传播链条、法定传染病分类和基本预防控制措施", [
            ("sec_epidem", "流行环节", "传染源、传播途径和易感人群", [
                ("传染源", ["source of infection"], "体内有病原体并能排出病原体的人或动物", "核心概念", 4),
                ("传播途径", ["route of transmission"], "病原体从传染源到易感者所经历的途径", "机制", 5),
                ("易感人群", ["susceptible population"], "对某种传染病缺乏特异性免疫力而容易感染的人群", "核心概念", 4),
                ("潜伏期", ["incubation period"], "病原体侵入机体到出现最初症状的时间", "表现", 3),
                ("隐性感染", ["inapparent infection"], "无明显临床症状但可产生免疫应答的感染", "机制", 3),
                ("病原携带状态", ["carrier state"], "无明显临床症状但携带并排出病原体的状态", "表现", 3),
            ]),
            ("sec_vaccine", "免疫预防", "主动免疫、被动免疫、疫苗种类和计划免疫程序", [
                ("疫苗", ["vaccine"], "用病原体制成的能诱导机体产生特异性免疫的生物制品", "治疗", 4),
                ("灭活疫苗", ["inactivated vaccine"], "物理或化学方法灭活病原体制成的疫苗", "治疗", 3),
                ("减毒活疫苗", ["live attenuated vaccine"], "经人工减毒处理仍保持免疫原性的活病原体疫苗", "治疗", 3),
                ("计划免疫", ["immunization program"], "按规定的免疫程序有计划地进行预防接种", "治疗", 3),
                ("群体免疫", ["herd immunity"], "人群中免疫个体比例足够高时阻断传播的保护效应", "核心概念", 3),
            ]),
        ]),
        ("ch_tb", "结核病", "结核病的病原学、流行病学、临床表现、诊断和治疗",
         "掌握肺结核的临床分型、诊断标准和化疗原则", [
            ("sec_tb_clinical", "结核病临床", "肺结核和肺外结核的临床表现、影像学特征和诊断", [
                ("原发型肺结核", ["primary pulmonary TB"], "初次感染结核菌引起的肺部病变，多见于儿童", "疾病", 4),
                ("继发型肺结核", ["secondary pulmonary TB"], "再次感染或潜伏感染激活引起的肺结核，多见于成人", "疾病", 4),
                ("结核性胸膜炎", ["tuberculous pleurisy"], "结核菌感染胸膜引起的炎症，表现为胸痛和胸腔积液", "疾病", 3),
                ("痰涂片检查", ["sputum smear"], "检测痰液中抗酸杆菌的快速诊断方法", "诊断", 4),
                ("结核菌素试验", ["TST"], "PPD皮内试验判断结核菌感染的免疫学方法", "诊断", 3),
                ("IGRA", ["interferon-gamma release assay"], "检测结核特异性IFN-γ释放的体外诊断方法", "诊断", 3),
                ("抗结核治疗", ["antituberculosis therapy"], "联合使用异烟肼、利福平等药物的长程标准化治疗", "治疗", 5),
            ]),
        ]),
        ("ch_hepatitis", "病毒性肝炎", "甲、乙、丙、丁、戊型肝炎病毒的传染源、传播途径、临床特点和防治",
         "掌握乙肝血清学标志物解读和肝炎预防措施", [
            ("sec_hep_b", "乙型肝炎", "乙肝病毒的抗原抗体系统和血清学诊断", [
                ("乙肝病毒", ["HBV"], "嗜肝DNA病毒，经血液、母婴和性接触传播", "病原体", 5),
                ("HBsAg", ["hepatitis B surface antigen"], "乙肝表面抗原，阳性表示HBV现症感染", "诊断", 4),
                ("HBeAg", ["hepatitis B e antigen"], "乙肝e抗原，阳性表示病毒复制活跃传染性强", "诊断", 3),
                ("乙肝疫苗", ["hepatitis B vaccine"], "基因重组HBsAg疫苗，阻断HBV母婴传播的最有效措施", "治疗", 4),
            ]),
            ("sec_hep_clinical", "肝炎临床表现", "急性黄疸型肝炎的分期：黄疸前期、黄疸期和恢复期", [
                ("急性黄疸型肝炎", ["acute icteric hepatitis"], "以黄疸、乏力、纳差和肝区疼痛为主要表现", "疾病", 4),
                ("肝酶升高", ["elevated liver enzymes"], "ALT/AST明显升高反映肝细胞损伤", "表现", 3),
                ("慢性肝炎", ["chronic hepatitis"], "病程超过6个月的肝脏持续性炎症", "疾病", 3),
            ]),
        ]),
    ]),
}

# ── Build all data ──
for bid, (title, pages, chapters) in DATA.items():
    # Register textbook
    db.merge(Textbook(id=bid, filename=f"{bid}.pdf", title=title, format="pdf",
        file_size=0, total_pages=pages, total_chars=pages * 2000,
        parse_status="completed", graph_status="completed", index_status="completed"))

    for ch_id, ch_name, ch_def, ch_obj, sections in chapters:
        cid = mkid(bid, ch_id)
        db.merge(KnowledgeNode(id=cid, name=ch_name, aliases=[], definition=ch_def,
            category="核心概念", importance=4, textbook_id=bid, textbook_title=title,
            chapter_title=ch_name, page=1, page_start=1, page_end=1,
            source_paragraph=ch_def, source_sentences=[ch_def],
            granularity="chapter_topic", learning_objective=ch_obj,
            quality_score=0.90, confidence=0.90,
            node_role="chapter", display_level="overview",
            parent_id="", created_by=SEED, source_type="demo_seed"))
        total_n += 1

        for sec_id, sec_name, sec_scope, concepts in sections:
            sid = mkid(bid, sec_id)
            db.merge(KnowledgeNode(id=sid, name=sec_name, aliases=[], definition=sec_scope,
                category="核心概念", importance=3, textbook_id=bid, textbook_title=title,
                chapter_title=ch_name, page=1, page_start=1, page_end=1,
                source_paragraph=sec_scope, source_sentences=[sec_scope],
                granularity="section_topic", learning_objective=sec_scope,
                quality_score=0.85, confidence=0.85,
                node_role="section", display_level="normal",
                parent_id=cid, created_by=SEED, source_type="demo_seed"))
            total_n += 1
            # chapter -> section
            db.add(KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", source=cid, target=sid,
                relation_type="contains", description=f"{ch_name}包含{sec_name}",
                confidence=0.95, relation_subtype="part_of", created_by=SEED))
            total_e += 1

            prev_cid = None
            for i, (name, aliases, defn, cat, imp) in enumerate(concepts):
                cid2 = mkid(bid, f"cc_{sec_id}_{i:02d}")
                db.merge(KnowledgeNode(id=cid2, name=name, aliases=aliases, definition=defn,
                    category=cat, importance=imp, textbook_id=bid, textbook_title=title,
                    chapter_title=ch_name, page=1, page_start=1, page_end=1,
                    source_paragraph=defn, source_sentences=[defn],
                    granularity="core_concept", learning_objective=f"理解{name}的定义与临床意义",
                    quality_score=0.80, confidence=0.80,
                    node_role="concept", display_level="normal",
                    parent_id=sid, created_by=SEED, source_type="demo_seed"))
                total_n += 1
                # section -> concept
                db.add(KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", source=sid, target=cid2,
                    relation_type="contains", description=f"{sec_name}包含{name}",
                    confidence=0.90, relation_subtype="part_of", created_by=SEED))
                total_e += 1
                # parallel with previous concept in same section
                if prev_cid:
                    db.add(KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", source=prev_cid, target=cid2,
                        relation_type="parallel", description=f"同属{sec_name}下的并列概念",
                        confidence=0.70, relation_subtype="sibling_of", created_by=SEED))
                    total_e += 1
                prev_cid = cid2

# ── Cross-textbook relations ──
CROSS = [
    ("book_05_cc_sec_inflame_def_00", "book_07_cc_sec_inflame_def_00", "parallel", "炎症在病理学与病理生理学中的互补描述"),
    ("book_04_cc_sec_tb_00", "book_06_cc_sec_tb_clinical_00", "applies_to", "结核分枝杆菌病原学应用于结核病临床理解"),
    ("book_02_cc_sec_conn_cell_01", "book_04_cc_sec_innate_04", "contains", "巨噬细胞是抗原递呈的关键细胞"),
    ("book_01_cc_sec_neck_vessel_02", "book_03_cc_sec_cv_reg_03", "applies_to", "迷走神经解剖位置对应其生理功能"),
    ("book_05_cc_sec_injury_type_01", "book_07_cc_sec_shock_mech_03", "applies_to", "坏死与DIC的病理联系"),
    ("book_03_cc_sec_bioelectric_01", "book_07_cc_sec_SIRS_00", "applies_to", "细胞电活动异常可触发炎症级联反应"),
    ("book_04_cc_sec_bac_infect_00", "book_06_cc_sec_epidem_01", "applies_to", "细菌内毒素致病机制与传染病传播的关联"),
    ("book_05_cc_sec_inflame_mediator_02", "book_07_cc_sec_mediator_pp_00", "parallel", "细胞因子在病理学和病理生理学中的描述互补"),
]
for src, tgt, rtype, desc in CROSS:
    db.add(KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", source=src, target=tgt,
        relation_type=rtype, description=desc, confidence=0.75,
        is_cross_textbook=True, created_by=SEED))
    total_e += 1

# ── Integration decisions ──
DECISIONS = [
    ("dec_inflame_merge", "merge", ["book_05_cc_sec_inflame_def_00", "book_07_cc_sec_inflame_def_00"],
     "炎症", "病理学和病理生理学对炎症的定义等价，均指活体组织对损伤的防御反应。病理学侧重形态变化，病理生理学侧重分子机制，合并为统一概念并保留互补说明。",
     0.92, 0.95, 0.88, 0.90, "合并后学生可从形态和机制两个维度全面理解炎症"),
    ("dec_SIRS_sepsis", "keep", ["book_07_cc_sec_SIRS_00", "book_07_cc_sec_SIRS_01"],
     "SIRS / 脓毒症", "SIRS为综合征描述，脓毒症为感染性SIRS的具体临床诊断，两者层级不同，保留并建立contains关系。",
     0.75, 0.82, 0.88, 0.87, "区分综合征与具体疾病有助于学生建立正确的临床思维"),
    ("dec_tb_cross", "keep", ["book_04_cc_sec_tb_00", "book_06_cc_sec_tb_clinical_00"],
     "结核分枝杆菌 / 结核病", "病原体与疾病为不同类别不可合并，保留两个节点并建立applies_to关系。",
     0.62, 0.70, 0.85, 0.93, "微生物学到传染病学的知识桥接，保持概念的医学分类正确性"),
    ("dec_cell_injury", "keep", ["book_05_cc_sec_injury_mech_00", "book_03_cc_sec_bioelectric_00"],
     "ATP耗竭 / 静息电位", "ATP耗竭影响钠钾泵功能进而影响静息电位，prerequisite关系不能合并。",
     0.35, 0.55, 0.80, 0.85, "连接病理学与生理学，展示细胞损伤对电活动的影响"),
    ("dec_complement", "merge", ["book_05_cc_sec_inflame_mediator_01", "book_04_cc_sec_innate_00"],
     "补体系统", "病理学和微生物学中对补体系统的描述一致，合并减少重复。",
     0.88, 0.92, 0.86, 0.91, "统一补体系统的定义，减少重复学习"),
]

for did, action, nodes, name, reason, sim_n, sim_d, sim_c, conf, effect in DECISIONS:
    db.merge(IntegrationDecision(id=did, action=action, affected_nodes=nodes,
        result_name=name, reason=reason, confidence=conf,
        similarity_name=sim_n, similarity_definition=sim_d, similarity_context=sim_c,
        evidence=[], alternatives_considered=["merge", "keep"],
        rejected_alternatives_reason="类别不同或定义不等价" if action == "keep" else "",
        risk="教师可复核" if conf < 0.88 else "",
        decision_effect=effect, created_by=SEED, teacher_override=False))
    total_d += 1

db.commit()
print(f"[COMPREHENSIVE] {total_n} nodes, {total_e} edges, {total_d} decisions")
# Count per book
for bid in sorted(DATA.keys()):
    n = db.query(KnowledgeNode).filter(KnowledgeNode.textbook_id == bid).count()
    e = db.query(KnowledgeEdge).filter(
        (KnowledgeEdge.source.in_(db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == bid)))
    ).count()
    print(f"  {DATA[bid][0]}: {n} nodes, {e} edges")
db.close()
