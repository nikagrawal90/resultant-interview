# app/scoring.py
from app.models import NormalizedRecord, PairDecision
from app.similarity import name_sim, address_sim, compare_domain
from app.config import WEIGHTS, THRESHOLDS, REVIEW_BAND, DOMAIN_VARIANT_SCORE

_CONF_CAP = {3: 99, 2: 95, 1: 90}

def score_pair(a: NormalizedRecord, b: NormalizedRecord) -> PairDecision:
    sims = {}
    if a.name and b.name:
        sims["name"] = name_sim(a.name, b.name)
    if a.address and b.address:
        sims["address"] = address_sim(a.address, b.address)

    dom = compare_domain(a.domain, b.domain)
    if dom == "exact":
        sims["domain"] = 1.0
    elif dom == "variant":
        sims["domain"] = DOMAIN_VARIANT_SCORE

    # Veto (#10): exact name+address but a genuinely different registrable-name domain.
    if (sims.get("name") == 1.0 and sims.get("address") == 1.0 and dom == "different"):
        return PairDecision(0.0, "no_merge", 0, "veto: conflicting domain")

    if not sims:
        return PairDecision(0.0, "no_merge", 0, "no comparable fields")

    total_w = sum(WEIGHTS[f] for f in sims)
    score = sum(WEIGHTS[f] * s for f, s in sims.items()) / total_w
    n = len(sims)
    conf = min(round(score * 100), _CONF_CAP[n])

    if n == 1:
        field, sim = next(iter(sims.items()))
        if sim == 1.0 and field == "domain":
            return PairDecision(score, "merge", conf, "single exact domain")
        if sim == 1.0:
            return PairDecision(score, "review", conf, f"single exact {field} (collides)")
        return PairDecision(score, "no_merge", conf, "single non-exact field")

    threshold = THRESHOLDS[n]
    if score >= threshold:
        return PairDecision(score, "merge", conf, f"score {score:.2f} >= {threshold}")
    if score >= threshold - REVIEW_BAND:
        return PairDecision(score, "review", conf, f"score {score:.2f} in review band")
    return PairDecision(score, "no_merge", conf, f"score {score:.2f} < band")
