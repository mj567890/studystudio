"""Generate test PDF about XSS attacks for C3 pipeline verification."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch

output_path = '/tmp/c3_test_xss.pdf'
doc = SimpleDocTemplate(output_path, pagesize=A4)

styles = getSampleStyleSheet()
cn_style = ParagraphStyle('CN', parent=styles['Normal'], fontSize=12, leading=18)
title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=18)
h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14)

story = []

# Title
story.append(Paragraph('Cross-Site Scripting (XSS) Attack and Defense Guide', title_style))
story.append(Spacer(1, 0.3 * inch))
story.append(Paragraph('A Comprehensive Guide to XSS Security', styles['Normal']))
story.append(Spacer(1, 0.5 * inch))

# Chapter 1
story.append(Paragraph('Chapter 1: XSS Attack Overview', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'Cross-Site Scripting (XSS) is a common web security vulnerability. '
    'Attackers inject malicious script code into target website pages. '
    'When other users visit the affected page, the malicious script executes '
    'in their browser, potentially stealing cookies, session tokens, '
    'redirecting users to phishing sites, or modifying page content. '
    'The root cause of XSS attacks is that the application fails to properly '
    'validate and sanitize user input before embedding it into HTML output. '
    'XSS attacks exploit the trust a user has for a particular website.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Chapter 2
story.append(Paragraph('Chapter 2: Three Types of XSS', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'XSS attacks are primarily classified into three types: Reflected XSS, '
    'Stored XSS, and DOM-based XSS. Reflected XSS is the most common type. '
    'The attacker constructs a URL containing malicious scripts and tricks '
    'the user into clicking it. The server reflects the script back in the '
    'response page. Stored XSS is more dangerous - malicious scripts are '
    'permanently stored on the target server (in databases, comment systems, etc.). '
    'Every time a user accesses a page containing the stored script, the attack '
    'triggers. DOM-based XSS occurs entirely on the client side, modifying the '
    'page DOM structure to execute malicious code, without the server response '
    'necessarily containing malicious content.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Chapter 3
story.append(Paragraph('Chapter 3: Reflected XSS in Detail', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'Reflected XSS occurs when the server embeds HTTP request parameters directly '
    'into the response page. A typical attack scenario: the attacker sends an email '
    'containing a malicious link where URL parameters include JavaScript code. '
    'For example: http://example.com/search?q=alert(document.cookie). '
    'When the user clicks the link, the server embeds the search term directly into '
    'the search results page, causing the script to execute in the browser. '
    'The key defense against Reflected XSS is HTML Entity Encoding: convert special '
    'characters like angle brackets, quotes, and ampersands into their corresponding '
    'HTML entities. This ensures user input is treated as data, not executable code. '
    'Additional defenses include input validation against a whitelist of allowed characters.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Chapter 4
story.append(Paragraph('Chapter 4: Stored XSS and Defense', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'Stored XSS (also known as Persistent XSS) is the most damaging XSS type. '
    'Attackers submit malicious scripts to the target website database - for example, '
    'posting comments containing script tags, or injecting JavaScript into user profiles. '
    'When other users browse this content, the malicious script is retrieved from the '
    'database and executed in their browsers. Stored XSS can form worm attacks that '
    'automatically propagate through social networks. Defense measures include: '
    'input validation using whitelist filtering, output encoding based on context '
    '(HTML encoding, JavaScript encoding, or URL encoding), using Content-Security-Policy '
    '(CSP) HTTP headers to restrict script execution sources, and setting HttpOnly cookie '
    'flags to prevent scripts from reading session cookies. Web Application Firewalls (WAF) '
    'can also help detect and block stored XSS payloads.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Chapter 5
story.append(Paragraph('Chapter 5: DOM-based XSS Principles', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'DOM-based XSS payloads do not pass through the server. The vulnerability arises '
    'from JavaScript code unsafely processing data from DOM data sources. Common unsafe '
    'data sources include: document.URL, document.location.hash, document.referrer, '
    'and window.name. Unsafe output methods include: innerHTML, document.write(), '
    'eval(), and setTimeout() with string arguments. For example, if a page contains: '
    'document.getElementById("content").innerHTML = location.hash.substring(1); '
    'an attacker can construct a URL to trigger XSS via the hash fragment. '
    'Defending against DOM-based XSS requires avoiding passing untrusted data to '
    'dangerous JavaScript methods, using textContent instead of innerHTML, and '
    'applying proper JavaScript encoding to user-controlled data before using it '
    'in the DOM context.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Chapter 6
story.append(Paragraph('Chapter 6: Comprehensive XSS Defense Strategy', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'Building a robust XSS defense requires a multi-layered protection strategy. '
    'First, secure coding standards: validate and filter all user input using whitelists '
    'rather than blacklists. Second, output encoding: choose the correct encoding scheme '
    'based on the output context (HTML Body, HTML Attribute, JavaScript, CSS, URL). '
    'Third, security response headers: Content-Security-Policy (CSP) is the most powerful '
    'defense mechanism - by declaring which resource sources are allowed, even if an '
    'attacker successfully injects a script, it cannot execute. The X-XSS-Protection '
    'header enables the browser built-in XSS filter. Fourth, use secure development '
    'frameworks: modern frontend frameworks like React and Vue automatically HTML-encode '
    'output by default, but developers must be cautious of dangerous APIs like '
    'dangerouslySetInnerHTML and v-html. Fifth, regular security testing: use automated '
    'scanning tools like OWASP ZAP and Burp Suite, combined with manual penetration '
    'testing, to verify the effectiveness of protective measures.',
    cn_style
))
story.append(Spacer(1, 0.3 * inch))

# Appendix
story.append(Paragraph('Appendix: Common Defense Code Examples', h2_style))
story.append(Spacer(1, 0.2 * inch))
story.append(Paragraph(
    'HTML Entity Encoding in JavaScript: '
    'function htmlEncode(str) { return String(str).replace(/&/g, "&amp;")'
    '.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")'
    '.replace(/\'/g, "&#x27;"); } '
    'Setting CSP header: Content-Security-Policy: default-src "self"; script-src "self" "nonce-random123" '
    'Using DOMPurify library to sanitize HTML content and remove potential malicious scripts. '
    'In Python Flask with Jinja2, auto-escaping is enabled by default. '
    'In Express.js, use helmet-csp middleware for CSP headers. '
    'Sanitize user input with validator.js: validator.escape(userInput)',
    cn_style
))

doc.build(story)
print(f'PDF generated: {output_path}')
print(f'Size: {os.path.getsize(output_path)} bytes')
