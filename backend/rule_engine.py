"""Heuristic signals, never automatic legal determinations."""
from datetime import date
from uuid import uuid4
from .models import AIssue, validate_issue
from .regulation_service import candidates


def detect(segments,kb,context):
    evidence=candidates(kb,context);issues=[]
    text='\n'.join(s['text'] for s in segments)
    mapping={s['segment_id']:s['text'] for s in segments}
    for rule in kb.rules:
        if not rule.enabled or context.material_type not in rule.applicable_material_types or context.channel not in rule.applicable_channels:continue
        for s in segments:
            for word in rule.detection.patterns:
                if not word:continue
                offset=0
                while True:
                    start=s['text'].find(word,offset)
                    if start<0:break
                    offset=start+len(word)
                    prefix=s['text'][max(0,start-24):start]
                    contextual=any(marker in prefix for marker in ['不得','禁止','不能','不应','反面示例','错误示例','不可'])
                    explanation=rule.explanation+'；'+rule.detection.context_note
                    if contextual:explanation='上下文包含否定或反面示例线索，本项降为低优先级待人工判断；'+explanation
                    i=AIssue(issue_id=str(uuid4()),risk_type=rule.risk_type,severity='low' if contextual else rule.severity,original_text=word,location={'segment_id':s['segment_id'],'start':start,'end':offset},reason=explanation,regulation_ids=rule.regulation_ids,suggestion='请结合产品合同及适用范围核实，删除或修正不准确表述并完善必要提示。')
                    checked=validate_issue(i,mapping,evidence,date.today(),context.material_type,context.channel)
                    checked.source='rule';issues.append(checked)
                    if len(issues)>=200:return issues
    # Absence detection anchors real text; it does not fabricate missing text or a legal mandate.
    for risk,keywords,explanation in [('disclosure',['风险','亏损','损失'],'全文未检出常见风险说明词，请人工确认是否需要补充风险告知'),('disclosure',['费用','费率','收费'],'全文未检出费用说明词，请人工核实是否适用费用披露义务')]:
        if context.material_type in ['marketing','product_intro'] and not any(k in text for k in keywords):
            s=segments[0];anchor=s['text'][:min(50,len(s['text']))]
            i=AIssue(issue_id=str(uuid4()),risk_type=risk,severity='low',original_text=anchor,location={'segment_id':s['segment_id'],'start':0,'end':len(anchor)},reason=explanation+'；缺词仅为启发式提示，否定/引用等语境需人工复核。',regulation_ids=[],suggestion='根据产品实际情况核实并补充清晰的信息，不编造费用或风险。')
            checked=validate_issue(i,mapping,evidence,date.today(),context.material_type,context.channel);checked.source='rule';issues.append(checked)
    return issues


def deduplicate(issues):
    result=[];seen=set()
    for issue in issues:
        key=(issue.location.segment_id,issue.location.start,issue.location.end,issue.risk_type,issue.reason if issue.source=='rule' and not issue.regulation_ids else '')
        if key not in seen:result.append(issue);seen.add(key)
    return result
