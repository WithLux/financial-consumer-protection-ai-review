"""Generate a report solely from reviewed content, never from rejected candidates."""
import io
import re
from docx import Document
from docx.shared import Cm, Pt
from docx.oxml.ns import qn

MATERIALS={'marketing':'营销宣传材料','product_intro':'金融产品介绍','notice':'客户告知材料'}
SEVERITIES={'high':'高风险','medium':'中风险','low':'低风险'}

def clean(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value or ''))


def build_report(review,draft):
    doc=Document();section=doc.sections[0]
    section.top_margin=section.bottom_margin=Cm(2.3)
    section.left_margin=section.right_margin=Cm(2.5)
    style=doc.styles['Normal'];style.font.name='Microsoft YaHei';style.font.size=Pt(10.5)
    style.element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    doc.add_heading('金融消费者权益保护审查意见书',0)
    if draft:doc.add_paragraph('未完成复核草稿 · 不得作为最终审查意见')
    doc.add_paragraph('独立产品Demo，仅作为人工审查辅助记录，非银行正式签批文件。')
    fields=review.get('report_fields') or {}
    table=doc.add_table(rows=0,cols=2);table.style='Table Grid'
    for label,value in [('审查编号',review['review_id']),('材料名称',review['filename']),('申请部门',fields.get('applicant_department','待填写')),('材料类型',MATERIALS.get(review['context']['material_type'],'待核实')),('审查人员',fields.get('reviewer','待填写')),('审查日期',fields.get('review_date','待填写')),('审查范围',fields.get('review_scope','待填写')),('材料哈希',review['sha256']),('法规库版本',review['library_version']),('确认版本',review.get('finalized_version') or '未确认')]:
        row=table.add_row().cells;row[0].text=label;row[1].text=clean(value)
    doc.add_heading('一、经人工确认的问题清单',1)
    issues=[i for i in review['issues'] if i['review_status'] in ['accepted','edited','added'] or (draft and i['review_status']=='pending')]
    doc.add_paragraph(f"问题清单数量：{len(issues)}；高风险{sum(i['severity']=='high' for i in issues)}、中风险{sum(i['severity']=='medium' for i in issues)}、低风险{sum(i['severity']=='low' for i in issues)}。以上为审查记录统计，不是模型准确率。")
    if not issues:doc.add_paragraph('当前无进入问题清单的项目；这不代表材料已通过全部合规审查。')
    for index,issue in enumerate(issues,1):
        doc.add_heading(f"{index}. {SEVERITIES.get(issue['severity'],issue['severity'])}"+('（待复核）' if issue['review_status']=='pending' else ''),2)
        for label,value in [('问题原文',issue['original_text']),('原文位置',issue['location']),('风险说明',issue['reason']),('修改建议',issue['suggestion']),('人工决定理由',issue.get('decision_reason') or '尚未复核')]:doc.add_paragraph(label+'：'+clean(value))
        for rid in issue['regulation_ids']:
            r=review['regulations'].get(rid)
            if r:
                doc.add_paragraph(f"法规依据ID：{rid}")
                doc.add_paragraph(clean(f"{r['name']} {r['article_number']}"))
                doc.add_paragraph('条款：'+clean(r['text']))
                doc.add_paragraph('官方来源：'+clean(r['source_url']))
                doc.add_paragraph('施行日期：'+clean(r['effective_at'])+'；核验日期：'+clean(r['verified_at']))
        if issue['reference_status']!='verified':doc.add_paragraph('法规依据待核实，不作确定法律认定。')
    doc.add_heading('二、最终审查结论',1);doc.add_paragraph(clean(fields.get('final_conclusion','尚未由审查人员填写整体意见')))
    doc.add_heading('三、整改建议及审查说明',1);doc.add_paragraph(clean(fields.get('remediation_notes','尚未填写')))
    doc.add_paragraph('解析及审查限制：'+clean('；'.join(review['coverage']['warnings'])))
    doc.add_paragraph('执行状态：'+clean(review['execution']))
    doc.add_paragraph('被驳回的问题不列入本清单；原始候选意见及操作审计仅在隔离任务中保留。审查统计不是模型准确率；未发现疑似问题不代表合规通过。')
    output=io.BytesIO();doc.save(output);return output.getvalue()
