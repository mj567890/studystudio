"""Generate Book C for incremental merge test — focused on Redis/CouchDB injection.
These topics are related to existing NoSQL content but introduce genuinely new concepts."""
import os
import fitz
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch

def build_pdf(output_path, title, chapters):
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    cn = ParagraphStyle("CN", parent=styles["Normal"], fontSize=12, leading=18)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14)

    story = [Paragraph(title, h1), Spacer(1, 0.3 * inch)]
    for ch_title, ch_content in chapters:
        story.append(PageBreak())
        story.append(Paragraph(ch_title, h2))
        story.append(Spacer(1, 0.2 * inch))
        for para in ch_content.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), cn))
                story.append(Spacer(1, 0.15 * inch))
    doc.build(story)

    fitz_doc = fitz.open(output_path)
    toc = [[1, ch[0], i+1] for i, ch in enumerate(chapters)]
    fitz_doc.set_toc(toc)
    fitz_doc.saveIncr()
    fitz_doc.close()
    print(f"  PDF: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path

BOOK_C_CHAPTERS = [
    ("Chapter 9: Redis Injection and Lua Script Security",
     "Redis, while primarily a key-value store, is vulnerable to injection attacks through "
     "its Lua scripting engine and command construction patterns. When applications build "
     "Redis commands by concatenating user input strings, attackers can inject additional "
     "commands or manipulate existing command semantics. The EVAL and EVALSHA commands are "
     "particularly dangerous as they execute Lua scripts with full server access.\n\n"
     "Redis injection defenses must focus on input sanitization before command construction. "
     "Use Redis client libraries that support parameter binding instead of raw command strings. "
     "Validate all user input against allowlists before passing to EVAL scripts. Consider using "
     "Redis ACLs to restrict which commands Lua scripts can execute. Monitor slow queries and "
     "unusual command patterns as indicators of injection attempts."),

    ("Chapter 10: CouchDB and Document Database Injection",
     "CouchDB uses JavaScript-based views and Mango queries, both of which introduce unique "
     "injection vectors. The JavaScript view server can be exploited through malicious input "
     "that breaks out of the intended query context. CouchDB's HTTP API accepts JSON query "
     "objects that can be manipulated to alter query semantics.\n\n"
     "Defending CouchDB requires validating all user input before incorporation into Mango "
     "query objects. Use CouchDB's built-in validation functions to enforce document schemas. "
     "Never pass raw user input to JavaScript map/reduce functions. Implement query complexity "
     "limits to prevent resource exhaustion attacks."),

    ("Chapter 11: Web Application Firewall for Database Attacks",
     "Web Application Firewalls (WAF) provide an additional defense layer against database "
     "injection attacks. Modern WAFs can detect and block injection attempts by analyzing "
     "HTTP request patterns, parameter values, and request frequency. For NoSQL injection, "
     "WAF rules must be specifically configured to detect NoSQL operators and syntax.\n\n"
     "WAF deployment requires careful tuning to balance security and usability. Overly "
     "aggressive rules can block legitimate requests. WAF should be combined with application-level "
     "input validation, not used as a replacement. Monitor WAF logs to identify new attack "
     "patterns and tune rules accordingly. Consider using cloud-based WAF services that provide "
     "automatic rule updates for emerging NoSQL injection techniques."),
]

build_pdf("/tmp/c5_book_c.pdf", "Redis, CouchDB & WAF Injection Defense", BOOK_C_CHAPTERS)
print("\nBook C generated: /tmp/c5_book_c.pdf")
