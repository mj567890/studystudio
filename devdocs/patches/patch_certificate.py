from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

NEW = '''
# ── 阶段能力证书 PDF ──────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import io
from datetime import datetime

@eight_dim_router.get("/learners/me/certificate")
async def download_certificate(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user["user_id"]

    # 查用户信息
    user_row = (await db.execute(text("""
        SELECT nickname, email FROM users WHERE user_id = CAST(:uid AS uuid)
    """), {"uid": uid})).fetchone()
    nickname = (user_row.nickname or user_row.email.split("@")[0]) if user_row else "学员"

    # 查主题信息和完成情况
    topic_row = (await db.execute(text("""
        SELECT name FROM skill_topics WHERE topic_key = :tk LIMIT 1
    """), {"tk": topic_key})).fetchone()
    topic_name = topic_row.name if topic_row else topic_key

    total = (await db.execute(text("""
        SELECT COUNT(*) FROM skill_chapters WHERE topic_key = :tk
    """), {"tk": topic_key})).scalar() or 0

    completed = (await db.execute(text("""
        SELECT COUNT(DISTINCT sc.chapter_id)
        FROM skill_chapters sc
        JOIN learner_chapter_progress lcp
          ON lcp.chapter_id = sc.chapter_id
         AND lcp.user_id = CAST(:uid AS uuid)
         AND lcp.status = 'completed'
        WHERE sc.topic_key = :tk
    """), {"uid": uid, "tk": topic_key})).scalar() or 0

    if total == 0 or completed < total:
        raise HTTPException(400, detail={
            "code": "CERT_001",
            "msg": f"尚未完成全部章节（{completed}/{total}），无法颁发证书"
        })

    await db.close()

    # 生成证书编号
    import hashlib
    cert_no = hashlib.md5(f"{uid}{topic_key}{datetime.utcnow().date()}".encode()).hexdigest()[:12].upper()
    issue_date = datetime.utcnow().strftime("%Y年%m月%d日")

    # 生成 PDF
    pdf_buf = _build_certificate_pdf(nickname, topic_name, issue_date, cert_no)

    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate_{topic_key}.pdf"'}
    )


def _build_certificate_pdf(name: str, topic: str, date: str, cert_no: str) -> io.BytesIO:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # 注册中文字体
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    font_name = "NotoSans"
    for fp in font_paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont(font_name, fp, subfontIndex=0))
            break
    else:
        font_name = "Helvetica"

    buf = io.BytesIO()
    W, H = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    # 背景
    c.setFillColor(colors.HexColor("#f8f6f0"))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # 外边框
    c.setStrokeColor(colors.HexColor("#c9a84c"))
    c.setLineWidth(4)
    c.rect(12*mm, 12*mm, W-24*mm, H-24*mm, fill=0, stroke=1)

    # 内边框
    c.setLineWidth(1.5)
    c.rect(16*mm, 16*mm, W-32*mm, H-32*mm, fill=0, stroke=1)

    # 顶部装饰线
    c.setStrokeColor(colors.HexColor("#c9a84c"))
    c.setLineWidth(1)
    c.line(40*mm, H-32*mm, W-40*mm, H-32*mm)

    # 标题：结业证书
    c.setFont(font_name, 42)
    c.setFillColor(colors.HexColor("#2c2c2c"))
    title = "结  业  证  书"
    c.drawCentredString(W/2, H-70*mm, title)

    # 副标题
    c.setFont(font_name, 14)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawCentredString(W/2, H-85*mm, "CERTIFICATE OF COMPLETION")

    # 分隔线
    c.setStrokeColor(colors.HexColor("#c9a84c"))
    c.setLineWidth(0.8)
    c.line(60*mm, H-92*mm, W-60*mm, H-92*mm)

    # 正文
    c.setFont(font_name, 16)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawCentredString(W/2, H-112*mm, "兹证明")

    # 姓名
    c.setFont(font_name, 32)
    c.setFillColor(colors.HexColor("#c9a84c"))
    c.drawCentredString(W/2, H-132*mm, name)

    # 姓名下划线
    name_w = c.stringWidth(name, font_name, 32)
    c.setStrokeColor(colors.HexColor("#c9a84c"))
    c.setLineWidth(1)
    c.line(W/2 - name_w/2 - 5, H-135*mm, W/2 + name_w/2 + 5, H-135*mm)

    # 完成内容
    c.setFont(font_name, 16)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawCentredString(W/2, H-152*mm, f"已完成「{topic}」全部学习内容")
    c.drawCentredString(W/2, H-165*mm, "具备该领域的系统知识与实践能力")

    # 底部信息
    c.setFont(font_name, 11)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawString(40*mm, 30*mm, f"颁发日期：{date}")
    c.drawCentredString(W/2, 30*mm, "StudyStudio 自适应学习平台")
    c.drawRightString(W-40*mm, 30*mm, f"证书编号：{cert_no}")

    c.save()
    buf.seek(0)
    return buf

'''

ANCHOR = "# ── 复习提醒"
if "download_certificate" in s:
    print("✓ 证书接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW + ANCHOR, 1))
    print("✓ 证书接口写入完成")
