"""Generate test PDFs for C4 and C5 verification."""
import os, fitz
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch

def build_pdf(output_path, title, chapters):
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    cn = ParagraphStyle('CN', parent=styles['Normal'], fontSize=12, leading=18)
    h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=18)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14)

    story = []
    story.append(Paragraph(title, h1))
    story.append(Spacer(1, 0.3 * inch))

    for ch_title, ch_content in chapters:
        story.append(PageBreak())
        story.append(Paragraph(ch_title, h2))
        story.append(Spacer(1, 0.2 * inch))
        for para in ch_content.split('\n\n'):
            if para.strip():
                story.append(Paragraph(para.strip(), cn))
                story.append(Spacer(1, 0.15 * inch))

    doc.build(story)

    # Add PDF outline/TOC using PyMuPDF
    fitz_doc = fitz.open(output_path)
    toc_entries = []
    page_num = 1
    for ch_title, _ in chapters:
        toc_entries.append([1, ch_title, page_num])
        page_num += 1
    fitz_doc.set_toc(toc_entries)
    fitz_doc.saveIncr()
    fitz_doc.close()

    print(f'PDF: {output_path} ({os.path.getsize(output_path)} bytes)')
    return output_path

# ===== C4 PDF: With TOC/outline =====
c4_chapters = [
    ("Chapter 1: CSRF Attack Fundamentals",
     "Cross-Site Request Forgery (CSRF) is an attack that forces authenticated users "
     "to submit unwanted requests to web applications. The attacker crafts a malicious "
     "web page that triggers requests to a target site where the victim is authenticated. "
     "When the victim visits the malicious page, the browser automatically sends the "
     "authenticated request to the target application.\n\n"
     "CSRF attacks exploit the trust that websites have in authenticated browsers. "
     "Unlike XSS which exploits user trust in websites, CSRF exploits website trust in users. "
     "The attack works because browsers automatically include credentials like session cookies "
     "with every request to the origin server."),

    ("Chapter 2: CSRF Token Defense Pattern",
     "The primary defense against CSRF is the synchronizer token pattern. Each form or "
     "state-changing request must include a random, unpredictable token that is bound to "
     "the user's session. The server generates this token, embeds it in forms, and validates "
     "it on submission.\n\n"
     "CSRF tokens must be unique per session, cryptographically random, and never transmitted "
     "via cookies (which would defeat the purpose). Implementation requires the server to "
     "generate the token, include it as a hidden form field, and validate it on the server "
     "side before processing any state-changing operation."),

    ("Chapter 3: SameSite Cookie Attribute",
     "The SameSite cookie attribute provides a powerful defense against CSRF. When set to "
     "'Strict', the browser only sends the cookie for same-site requests. When set to 'Lax', "
     "the browser sends the cookie for top-level navigations but not for cross-site subrequests "
     "like form POSTs or AJAX calls.\n\n"
     "SameSite=Lax is the modern default in most browsers. Combined with CSRF tokens, it "
     "provides defense in depth. For APIs that need cross-site access, the SameSite=None; Secure "
     "configuration allows cross-site requests while ensuring HTTPS transport."),

    ("Chapter 4: Origin and Referer Header Validation",
     "The Origin and Referer HTTP headers can be used as an additional CSRF defense layer. "
     "By checking that the Origin header matches the expected domain, the server can reject "
     "requests originating from malicious sites.\n\n"
     "However, these headers have limitations: some browsers omit them in certain scenarios, "
     "privacy settings may strip them, and they can be spoofed in some configurations. "
     "Therefore, header validation should supplement, not replace, CSRF tokens."),

    ("Chapter 5: Advanced CSRF Protection Patterns",
     "Beyond the basics, several advanced patterns strengthen CSRF defense. Double-submit "
     "cookies use a cookie value that must match a request parameter. Custom request headers "
     "leverage the same-origin policy, as custom headers cannot be set cross-origin without "
     "CORS preflight. Encrypted token patterns encode session information within the token "
     "itself, eliminating server-side storage requirements.\n\n"
     "Stateless CSRF protection using HMAC-signed tokens allows horizontal scaling without "
     "shared session storage. Each token encodes the user ID and an expiry timestamp, signed "
     "with a server-side secret key. This approach is particularly suitable for microservices "
     "architectures."),
]

build_pdf('/tmp/c4_csrf_test.pdf', 'Cross-Site Request Forgery Defense Guide', c4_chapters)

# ===== C5 PDF: Second book for merge test =====
c5_chapters = [
    ("Advanced XSS Filter Evasion Techniques",
     "Attackers constantly develop new methods to bypass XSS filters and WAF rules. "
     "Understanding these evasion techniques is essential for security professionals. "
     "Common evasion methods include: character encoding tricks like UTF-7 XSS, "
     "hexadecimal and octal encoding of HTML entities, JavaScript string.fromCharCode "
     "obfuscation, and multibyte character sequences that bypass blacklist filters.\n\n"
     "Polyglot XSS payloads combine multiple context-breaking sequences into a single "
     "string, allowing the payload to execute in HTML body, attribute, and JavaScript "
     "contexts simultaneously. These payloads are particularly effective against "
     "incomplete output encoding implementations."),

    ("Content Security Policy Deep Dive",
     "Content-Security-Policy (CSP) is a computer security standard introduced to prevent "
     "XSS, clickjacking, and other code injection attacks. CSP works by declaring which "
     "dynamic resources are allowed to load. The policy is delivered via HTTP response "
     "headers or HTML meta tags.\n\n"
     "Key CSP directives include: default-src (fallback for all resource types), "
     "script-src (valid JavaScript sources), style-src (CSS sources), img-src (image sources), "
     "connect-src (AJAX/WebSocket endpoints). The nonce-source and hash-source mechanisms "
     "allow inline scripts with cryptographic validation. CSP report-only mode enables "
     "monitoring without enforcement, helping teams safely deploy policies."),

    ("Subresource Integrity and Trusted Types",
     "Subresource Integrity (SRI) ensures that resources fetched from CDNs or third parties "
     "are delivered without unexpected manipulation. By providing a cryptographic hash of "
     "the expected resource, browsers verify the integrity of fetched files.\n\n"
     "Trusted Types is a newer browser API that eliminates DOM XSS by requiring developers "
     "to use typed objects instead of strings when interacting with injection sinks like "
     "innerHTML and document.write. Combined with a strict CSP, Trusted Types can eliminate "
     "DOM-based XSS vulnerabilities at the platform level. TypeScript integration makes "
     "Trusted Types enforcement part of the development workflow."),
]

build_pdf('/tmp/c5_xss_advanced.pdf', 'Advanced XSS Defense Techniques', c5_chapters)

print("\nBoth PDFs generated successfully!")
print("C4 PDF: /tmp/c4_csrf_test.pdf (CSRF with TOC)")
print("C5 PDF: /tmp/c5_xss_advanced.pdf (Advanced XSS content)")
