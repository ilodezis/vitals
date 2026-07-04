"""VCF parsing core for the genetics module (pure, no DB / no I/O).

Parses a ``.vcf`` line into a :class:`ParsedVariant`, derives the genotype from the
sample column, and maps clinically actionable rsIDs to conflict-engine ``marker``
slugs via the curated :data:`INTERPRETATIONS` table. This lives in
``vitals/services`` (not ``scripts/``) so both the web router and the CLI importer
call the same domain logic — ``web/`` must never depend on ``scripts/``.

The CLI wrapper (``scripts/import_vcf.py``) re-exports these names and adds the
DB/argparse layer; ``web/routers/genetics.py`` imports directly from here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Curated interpretations of well-studied SNPs, organised by domain. Each entry
# fills the genetic_variants fields; ``marker`` + ``risk_alt`` are set ONLY where
# a non-reference allele has a concrete supplement-safety consequence worth
# feeding the conflict engine (currently iron + G6PD). Everything else is
# informational — gene/impact/interpretation/action are always populated so the
# catalog row is useful, and the genotype is shown alongside so the user sees
# carrier vs homozygous. Not medical advice; a navigator, not an enforcer.
#
# Allele conventions: ``risk_alt=True`` means the marker is stamped when the
# sample carries at least one ALT allele (carrier or homozygous). For purely
# informational rows the effect allele is described in the text, since consumer
# VCFs report the genotype relative to the reference build.
INTERPRETATIONS: dict[str, dict] = {
    # ── Iron / minerals ──────────────────────────────────────────────────────
    "rs1800562": {  # HFE C282Y
        "gene": "HFE",
        "marker": "hemochromatosis_carrier",
        "impact": "Накопление железа (гемохроматоз, C282Y)",
        "impact_domain": "supplements",
        "interpretation": "C282Y — главный вариант наследственного гемохроматоза. Гомозигота резко повышает риск перегрузки железом, носительство — умеренно.",
        "action_notes": "Не принимать препараты железа без подтверждённого дефицита (ферритин/трансферрин). Осторожно с высокими дозами витамина C вместе с железом.",
        "risk_alt": True,
    },
    "rs1799945": {  # HFE H63D
        "gene": "HFE",
        "marker": "hemochromatosis_carrier",
        "impact": "Накопление железа (гемохроматоз, H63D)",
        "impact_domain": "supplements",
        "interpretation": "H63D — более мягкий вклад в перегрузку железом; клинически значим в основном в сочетании с C282Y.",
        "action_notes": "Осторожно с препаратами железа; ориентироваться на ферритин.",
        "risk_alt": True,
    },
    # ── Folate / methylation / B-vitamins ────────────────────────────────────
    "rs1801133": {  # MTHFR C677T — ref=C, alt=T (confirmed dbSNP/ClinVar)
        "gene": "MTHFR",
        "impact": "Метаболизм фолата (C677T)",
        "impact_domain": "supplements",
        "interpretation": "T-аллель снижает активность MTHFR (CT ~65%, TT ~30%), хуже превращается фолиевая кислота в активную форму; может расти гомоцистеин.",
        "action_notes": "При T-аллеле предпочтительна метильная форма (L-метилфолат) вместо фолиевой кислоты; следить за B12/B6 и гомоцистеином.",
        "marker_by_zygosity": {"het": "mthfr_heterozygous", "hom_alt": "mthfr_c677t_homozygous"},
    },
    "rs1801131": {  # MTHFR A1298C
        "gene": "MTHFR",
        "impact": "Метаболизм фолата (A1298C)",
        "impact_domain": "supplements",
        "interpretation": "A1298C слабее влияет на активность фермента, чем C677T; значим в комбинации с ним.",
        "action_notes": "Учитывать вместе с C677T при выборе формы фолата.",
    },
    "rs602662": {  # FUT2 secretor
        "gene": "FUT2",
        "impact": "Статус витамина B12 (секреторный статус)",
        "impact_domain": "supplements",
        "interpretation": "Варианты FUT2 влияют на сывороточный B12 и состав микробиоты (секретор/несекретор).",
        "action_notes": "Контролировать B12 (актив. B12/голотранскобаламин), особенно на растительном рационе.",
    },
    "rs7946": {  # PEMT
        "gene": "PEMT",
        "impact": "Потребность в холине",
        "impact_domain": "supplements",
        "interpretation": "Сниженная активность PEMT повышает потребность в пищевом холине (особенно актуально без яиц/печени).",
        "action_notes": "Обеспечить достаточный холин (яйца, лецитин); при дефиците рассмотреть добавку.",
    },
    # ── Vitamin D ─────────────────────────────────────────────────────────────
    "rs2282679": {  # GC (vitamin D binding protein)
        "gene": "GC",
        "impact": "Уровень витамина D (транспортный белок)",
        "impact_domain": "supplements",
        "interpretation": "Минорный аллель GC ассоциирован с более низким 25(OH)D — труднее держать нормальный уровень.",
        "action_notes": "Контролировать 25(OH)D; вероятна потребность в более высокой поддерживающей дозе D3 + K2.",
    },
    "rs10741657": {  # CYP2R1
        "gene": "CYP2R1",
        "impact": "Синтез витамина D (25-гидроксилаза)",
        "impact_domain": "supplements",
        "interpretation": "Вариант CYP2R1 влияет на превращение витамина D в 25(OH)D.",
        "action_notes": "Учитывать при подборе дозы D3 по анализам.",
    },
    # ── Fatty acids / vitamin A ───────────────────────────────────────────────
    "rs174537": {  # FADS1
        "gene": "FADS1",
        "impact": "Конверсия омега-3/6 (ALA→EPA/DHA)",
        "impact_domain": "supplements",
        "interpretation": "Минорный аллель снижает активность десатуразы — растительная ALA хуже превращается в EPA/DHA.",
        "action_notes": "Предпочесть прямые EPA/DHA (рыбий жир/водорослевое масло), а не льняное масло.",
    },
    "rs7501331": {  # BCO1 (beta-carotene → retinol)
        "gene": "BCO1",
        "impact": "Конверсия бета-каротина в витамин A",
        "impact_domain": "supplements",
        "interpretation": "T-аллель снижает превращение бета-каротина в ретинол — «плохой конвертер».",
        "action_notes": "Не полагаться только на бета-каротин; рассмотреть преформированный витамин A (ретинол) из пищи.",
    },
    # ── Antioxidant / detox ───────────────────────────────────────────────────
    "rs4880": {  # SOD2 A16V
        "gene": "SOD2",
        "impact": "Антиоксидантная защита митохондрий",
        "impact_domain": "supplements",
        "interpretation": "Вариант SOD2 влияет на транспорт супероксиддисмутазы в митохондрии и окислительный стресс.",
        "action_notes": "Поддерживать кофакторы (Mn, Zn, Cu в балансе); богатый антиоксидантами рацион.",
    },
    "rs1695": {  # GSTP1
        "gene": "GSTP1",
        "impact": "Детоксикация (глутатион-S-трансфераза)",
        "impact_domain": "supplements",
        "interpretation": "Вариант снижает активность GSTP1 — детоксикация ксенобиотиков/оксидативный клиренс.",
        "action_notes": "Поддержка глутатиона (сон, белок, серосодержащие овощи, NAC по показаниям).",
    },
    "rs1050828": {  # G6PD (A- Val68Met)
        "gene": "G6PD",
        "marker": "g6pd_deficiency",
        "impact": "Дефицит G6PD (риск гемолиза)",
        "impact_domain": "supplements",
        "interpretation": "Дефицит G6PD повышает риск гемолиза при окислительном стрессе. Сцеплен с X-хромосомой.",
        "action_notes": "Избегать высоких доз витамина C (в/в), менадиона (вит. K3), бобов фава и ряда препаратов. Обсудить с врачом.",
        "risk_alt": True,
    },
    # ── Caffeine / stimulants / sleep ─────────────────────────────────────────
    "rs762551": {  # CYP1A2 — ref=A (fast/*1F), alt=C (slow/*1A) (confirmed SNPedia)
        "gene": "CYP1A2",
        "impact": "Скорость метаболизма кофеина",
        "impact_domain": "supplements",
        "interpretation": "AA — «быстрый» метаболизатор кофеина; носители C — «медленные», у них кофеин дольше действует и сильнее влияет на давление/сон.",
        "action_notes": "Медленным — ограничить кофеин, не пить во второй половине дня; следить за давлением.",
        "marker": "cyp1a2_slow_metabolizer",
        "risk_alt": True,
    },
    "rs5751876": {  # ADORA2A
        "gene": "ADORA2A",
        "impact": "Тревожность и сон от кофеина",
        "impact_domain": "supplements",
        "interpretation": "Вариант ADORA2A повышает чувствительность к кофеину — тревога и нарушение сна даже от умеренных доз.",
        "action_notes": "Снизить дозу кофеина; избегать стимуляторов вечером.",
    },
    # ── Alcohol ──────────────────────────────────────────────────────────────
    "rs671": {  # ALDH2
        "gene": "ALDH2",
        "impact": "Метаболизм алкоголя (ацетальдегид)",
        "impact_domain": "supplements",
        "interpretation": "A-аллель (ALDH2*2) резко снижает расщепление ацетальдегида — «флаш-реакция», выше риск при употреблении алкоголя.",
        "action_notes": "Минимизировать алкоголь — повышенный канцерогенный риск при флаш-реакции.",
    },
    "rs1229984": {  # ADH1B
        "gene": "ADH1B",
        "impact": "Скорость окисления алкоголя",
        "impact_domain": "supplements",
        "interpretation": "Вариант ADH1B ускоряет превращение этанола в ацетальдегид (быстрее наступает дискомфорт).",
        "action_notes": "Учитывать индивидуальную переносимость алкоголя.",
    },
    # ── Metabolic / weight / GLP-1 relevant ───────────────────────────────────
    "rs9939609": {  # FTO
        "gene": "FTO",
        "impact": "Аппетит и склонность к набору веса",
        "impact_domain": "weight",
        "interpretation": "A-аллель FTO ассоциирован с повышенным аппетитом и риском ожирения, но эффект хорошо корректируется белком и нагрузкой.",
        "action_notes": "Акцент на белок, контроль порций, регулярные тренировки; вариант не приговор.",
    },
    "rs17782313": {  # MC4R
        "gene": "MC4R",
        "impact": "Насыщение и аппетит",
        "impact_domain": "weight",
        "interpretation": "Вблизи MC4R — путь регуляции насыщения; C-аллель ассоциирован с большим аппетитом/ИМТ.",
        "action_notes": "Структурировать приёмы пищи, белок и клетчатка для насыщения.",
    },
    "rs7903146": {  # TCF7L2
        "gene": "TCF7L2",
        "impact": "Риск диабета 2 типа, секреция инсулина",
        "impact_domain": "glp1",
        "interpretation": "T-аллель — один из сильнейших общих факторов риска СД2, влияет на секрецию инсулина (важно в контексте GLP-1/метаболизма).",
        "action_notes": "Контроль гликемии (HbA1c, глюкоза натощак); поддерживать чувствительность к инсулину нагрузкой и составом тела.",
    },
    "rs1801282": {  # PPARG Pro12Ala
        "gene": "PPARG",
        "impact": "Чувствительность к инсулину",
        "impact_domain": "glp1",
        "interpretation": "Ala-аллель (Pro12Ala) обычно ассоциирован с лучшей чувствительностью к инсулину и меньшим риском СД2.",
        "action_notes": "Информативно; поддерживать метаболическое здоровье общими мерами.",
    },
    # ── Fitness / performance ─────────────────────────────────────────────────
    "rs1815739": {  # ACTN3 R577X
        "gene": "ACTN3",
        "impact": "Мышечный тип (сила/спринт vs выносливость)",
        "impact_domain": "workouts",
        "interpretation": "RR/RX — есть альфа-актинин-3 (наклон к силе/спринту); XX («ген стоп») — нет белка, чаще профиль выносливости.",
        "action_notes": "Информативно для акцентов в тренировках; не ограничивает прогресс.",
    },
    "rs8192678": {  # PPARGC1A
        "gene": "PPARGC1A",
        "impact": "Аэробная выносливость (биогенез митохондрий)",
        "impact_domain": "workouts",
        "interpretation": "Вариант PGC-1α влияет на митохондриальный биогенез и отклик на аэробные нагрузки.",
        "action_notes": "Информативно для планирования кардио/выносливости.",
    },
    # ── Neuro / stress / mood ─────────────────────────────────────────────────
    "rs4680": {  # COMT Val158Met — ref=G (Val, fast), alt=A (Met, slow) (confirmed)
        "gene": "COMT",
        "impact": "Дофамин, стресс-устойчивость, болевая чувствительность",
        "impact_domain": "supplements",
        "interpretation": "Val (быстрый клиренс дофамина) — «воин»: устойчивее к стрессу, но ниже базовый дофамин; Met (медленный) — «волнующийся»: выше когнитивный тонус, чувствительнее к стрессу/боли.",
        "action_notes": "Информативно для управления стрессом/восстановлением; при Met/Met — осторожнее со стимуляторами (кофеин, высокие дозы EGCG).",
        # Only the homozygous-Met genotype gets a firm marker — heterozygotes are
        # genuinely intermediate, not clearly "slow", so left informational-only.
        "marker_by_zygosity": {"hom_alt": "comt_slow_metabolizer"},
    },
    "rs6265": {  # BDNF Val66Met
        "gene": "BDNF",
        "impact": "Нейропластичность, настроение, отклик на нагрузку",
        "impact_domain": "system",
        "interpretation": "Met-аллель снижает секрецию BDNF — может влиять на память, настроение и нейропластический ответ на упражнения.",
        "action_notes": "Регулярная аэробная нагрузка и сон поддерживают BDNF.",
    },
    # ── Lactose ──────────────────────────────────────────────────────────────
    "rs4988235": {  # MCM6/LCT
        "gene": "MCM6",
        "impact": "Переносимость лактозы",
        "impact_domain": "supplements",
        "interpretation": "T-аллель обеспечивает персистенцию лактазы (переносимость молока во взрослом возрасте); CC — вероятна непереносимость лактозы.",
        "action_notes": "При CC — ограничить лактозу или использовать лактазу; следить за источниками кальция.",
    },
    # ── Pharmacogenetics (informational — обсуждать с врачом) ──────────────────
    "rs4244285": {  # CYP2C19*2
        "gene": "CYP2C19",
        "impact": "Метаболизм препаратов (клопидогрел, ИПП)",
        "impact_domain": "system",
        "interpretation": "*2 — нефункциональный аллель: снижен метаболизм ряда лекарств (клопидогрел — слабее эффект; ИПП — выше концентрация).",
        "action_notes": "Фармакогенетика — учитывать врачу при назначении соответствующих препаратов.",
    },
    "rs9923231": {  # VKORC1
        "gene": "VKORC1",
        "impact": "Чувствительность к варфарину",
        "impact_domain": "system",
        "interpretation": "Вариант VKORC1 повышает чувствительность к варфарину (нужна меньшая доза).",
        "action_notes": "Релевантно только при терапии варфарином — решает врач.",
    },
    "rs1057910": {  # CYP2C9*3
        "gene": "CYP2C9",
        "impact": "Метаболизм препаратов (варфарин, НПВП)",
        "impact_domain": "system",
        "interpretation": "*3 заметно снижает активность CYP2C9 — медленнее метаболизм варфарина и некоторых НПВП.",
        "action_notes": "Фармакогенетика — учитывать врачу.",
    },
    # ── Lipids / cardio (APOE требует двух SNP вместе) ────────────────────────
    "rs429358": {  # APOE
        "gene": "APOE",
        "impact": "ApoE-генотип (липиды, риск; часть пары)",
        "impact_domain": "labs",
        "interpretation": "Один из двух SNP, определяющих ApoE (E2/E3/E4). Полная интерпретация требует и rs7412. E4 ассоциирован с худшим липидным профилем и рисками — но это вероятность, не диагноз.",
        "action_notes": "Интерпретировать только вместе с rs7412; не делать выводов по одному SNP.",
    },
    "rs7412": {  # APOE
        "gene": "APOE",
        "impact": "ApoE-генотип (липиды, риск; часть пары)",
        "impact_domain": "labs",
        "interpretation": "Второй SNP пары ApoE. Совместно с rs429358 определяет изоформу E2/E3/E4.",
        "action_notes": "Интерпретировать вместе с rs429358; ориентироваться на реальный липидный профиль.",
    },
    # ── Skin barrier ──────────────────────────────────────────────────────────
    "rs61816761": {  # FLG R501X
        "gene": "FLG",
        "impact": "Барьер кожи (филаггрин)",
        "impact_domain": "skincare",
        "interpretation": "Нулевые мутации FLG нарушают кожный барьер — выше риск сухости, атопического дерматита, трансэпидермальной потери воды.",
        "action_notes": "Акцент на восстановление барьера: церамиды, увлажнение, мягкое очищение; осторожнее с агрессивными активами.",
    },
}


@dataclass(frozen=True)
class ParsedVariant:
    rsid: str
    ref: str
    alt: str
    genotype: str  # e.g. "A/G"; "./." when missing


def _genotype_from_gt(gt_field: str, ref: str, alts: list[str]) -> str:
    """Map a GT subfield (e.g. '0/1', '1|1') to an allele string ('A/G')."""
    raw = gt_field.replace("|", "/").split("/")
    alleles = [ref] + alts
    out: list[str] = []
    for token in raw:
        if token == "." or not token.isdigit():
            out.append(".")
            continue
        idx = int(token)
        out.append(alleles[idx] if 0 <= idx < len(alleles) else ".")
    return "/".join(out) if out else "./."


def parse_vcf_line(line: str) -> Optional[ParsedVariant]:
    """Parse one VCF data line into a ParsedVariant, or None for headers/blanks/
    lines without an rsID or genotype."""
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        return None
    cols = line.split("\t")
    if len(cols) < 10:
        return None
    rsid = cols[2].strip()
    if not rsid or rsid == "." or not rsid.startswith("rs"):
        return None
    ref = cols[3].strip()
    alts = [a.strip() for a in cols[4].split(",") if a.strip() and a.strip() != "."]
    fmt = cols[8].split(":")
    sample = cols[9].split(":")
    if "GT" not in fmt:
        return None
    gt = sample[fmt.index("GT")] if fmt.index("GT") < len(sample) else "./."
    genotype = _genotype_from_gt(gt, ref, alts)
    return ParsedVariant(rsid=rsid, ref=ref, alt=",".join(alts) or ".", genotype=genotype)


def _zygosity(genotype: str, ref: str) -> Optional[str]:
    """Classify a two-allele genotype relative to the VCF's REF allele:
    ``"hom_ref"`` (e.g. C/C), ``"het"`` (C/T), ``"hom_alt"`` (T/T), or ``None``
    for anything else (missing/haploid/multi-allelic)."""
    alleles = [a for a in genotype.split("/") if a and a != "."]
    if len(alleles) != 2:
        return None
    ref_count = sum(1 for a in alleles if a == ref)
    if ref_count == 2:
        return "hom_ref"
    if ref_count == 1:
        return "het"
    return "hom_alt"


def interpret(variant: ParsedVariant) -> dict:
    """Build the genetic_variants field dict for a parsed variant, applying a
    curated interpretation/marker when the rsID is known and the risk allele is
    present."""
    fields: dict = {
        "gene": "unknown",
        "rsid": variant.rsid,
        "genotype": variant.genotype,
    }
    info = INTERPRETATIONS.get(variant.rsid)
    if info is None:
        return fields

    alleles = set(variant.genotype.replace("/", " ").split())
    ref_alleles = {variant.ref}
    has_alt = bool(alleles - ref_alleles - {"."})

    fields["gene"] = info["gene"]
    fields["impact"] = info.get("impact")
    fields["impact_domain"] = info.get("impact_domain")
    fields["interpretation"] = info.get("interpretation")
    fields["action_notes"] = info.get("action_notes")

    zygosity_markers = info.get("marker_by_zygosity")
    if zygosity_markers:
        # Zygosity-aware entries (e.g. MTHFR het vs hom) — a distinct marker per
        # genotype, only for whichever zygosities the entry actually maps.
        zyg = _zygosity(variant.genotype, variant.ref)
        marker = zygosity_markers.get(zyg) if zyg else None
        if marker:
            fields["marker"] = marker
    else:
        # Only stamp the conflict marker when the entry defines one AND the risk
        # allele is actually present (carrier or homozygous) — the simpler,
        # zygosity-blind case (e.g. HFE, G6PD, CYP1A2).
        marker = info.get("marker")
        if marker and info.get("risk_alt") and has_alt:
            fields["marker"] = marker
    return fields


def iter_parsed(lines) -> list[ParsedVariant]:
    out = []
    for line in lines:
        parsed = parse_vcf_line(line)
        if parsed is not None:
            out.append(parsed)
    return out
