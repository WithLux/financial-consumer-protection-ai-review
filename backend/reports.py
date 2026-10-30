import io
from docx import Document


def build_report(review,draft):
    doc=Document();doc.add_heading('未完成复核草稿' if draft else '金融消保人工复核意见书',0)
    doc.add_paragraph('独立Demo辅助意见，非银行正式签批；AI或规则未发现问题不代表合规通过。')
    doc.add_paragraph(f"任务：{review['review_id']} / 版本：{review.get('finalized_version') or review['version']}")
    doc.add_paragraph('材料SHA256：'+review['sha256'])
    doc.add_paragraph('法规库版本：'+review['library_version'])
    doc.add_paragraph('执行状态：'+str(review['execution']))
    doc.add_paragraph('解析及审查限制：'+'；'.join(review['coverage']['warnings']))
    for index,i in enumerate(review['issues'],1):
        doc.add_heading(f"{index}. {i['risk_type']} / {i['severity']} / {i['review_status']}",2)
        for line in [i['original_text'],'位置：'+str(i['location']),'分析：'+i['reason'],'人工决定：'+(i.get('decision_reason') or '尚未复核')]:doc.add_paragraph(line)
        if i['review_status']!='rejected':doc.add_paragraph('修改建议：'+i['suggestion'])
        for rid in i['regulation_ids']:
            r=review['regulations'].get(rid)
            doc.add_paragraph(f"依据：{r['name']} {r['article_number']} {r['source_url']}" if r else '依据待核实：'+rid)
        if i['reference_status']!='verified':doc.add_paragraph('法规适用依据待核实，不作确定法律认定。')
    doc.add_heading('操作记录',1)
    for event in review.get('events',[]):doc.add_paragraph(f"{event['at']} / {event['action']} / {event['actor']}")
    output=io.BytesIO();doc.save(output);return output.getvalue()
