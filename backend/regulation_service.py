from datetime import date
from .config import ROOT
from .models import KnowledgeBase


def load_library():
    kb=KnowledgeBase.model_validate_json((ROOT/'data/regulations/regulations.json').read_text())
    # Rules are separately maintainable, with referential integrity rechecked after loading.
    import json
    rules=json.loads((ROOT/'data/regulations/rules.json').read_text())
    return KnowledgeBase.model_validate({**kb.model_dump(),'rules':rules})


def candidates(kb,context):
    today=date.today()
    selected=[]
    for r in kb.regulations:
        if r.verification_status!='verified' or not(r.effective_at<=today and (r.expires_at is None or today<r.expires_at)):continue
        if context.material_type not in r.applicable_material_types or context.channel not in r.applicable_channels:continue
        # Narrow financial-product-specific rule; conservative unknown products stay unverified.
        if r.regulation_id=='REG-NET-10-3' and not any(x in context.product_type for x in ['理财','资管','投资顾问','咨询']):continue
        selected.append(r)
    return KnowledgeBase(schema_version='1.0',version=kb.version,regulations=selected,rules=[])
